"""In-memory job repository with lazy expiration.

Jobs are kept in process memory; a single uvicorn worker is assumed (see
README). Sources and derived artefacts live on disk under STORAGE_DIR.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone

from config import settings
from schemas.jobs import JobStatus
from schemas.ocr import OCRBlock, OCRTable
from services.storage import remove_job_files

TERMINAL_STATUSES = frozenset(
    {JobStatus.completed, JobStatus.failed, JobStatus.expired}
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_job_id() -> str:
    return uuid.uuid4().hex


@dataclass
class Job:
    job_id: str
    status: JobStatus
    progress: int
    created_at: datetime
    completed_at: datetime | None
    file_name: str
    language: str | None
    resolved_language: str | None
    engine: str
    detect_table: bool
    detect_layout: bool
    callback_url: str | None
    source_type: str
    source_path: str | None = None
    source_url: str | None = None
    content_type: str | None = None
    page_numbers: list[int] | None = None
    text: str = ""  # never None: failed OCR yields an empty string
    confidence: float = 0.0
    pages: int = 0
    blocks: list[OCRBlock] = field(default_factory=list)
    tables: list[OCRTable] = field(default_factory=list)
    error: str | None = None


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ reads

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            self._apply_expiry(job)
            return replace(job)

    def list(
        self,
        *,
        page: int,
        page_size: int,
        status: JobStatus | None,
    ) -> tuple[int, list[Job]]:
        with self._lock:
            for job in self._jobs.values():
                self._apply_expiry(job)

            jobs = [
                job
                for job in self._jobs.values()
                if status is None or job.status == status
            ]
            jobs.sort(key=lambda job: (job.created_at, job.job_id), reverse=True)

            total = len(jobs)
            start = (page - 1) * page_size
            return total, [replace(job) for job in jobs[start : start + page_size]]

    # ----------------------------------------------------------------- writes

    def create(
        self,
        *,
        file_name: str,
        language: str | None,
        engine: str,
        detect_table: bool,
        detect_layout: bool,
        callback_url: str | None,
        source_type: str,
        source_path: str | None = None,
        source_url: str | None = None,
        content_type: str | None = None,
        page_numbers: list[int] | None = None,
        job_id: str | None = None,
    ) -> Job:
        job = Job(
            job_id=job_id or new_job_id(),
            status=JobStatus.pending,
            progress=0,
            created_at=utcnow(),
            completed_at=None,
            file_name=file_name,
            language=language,
            resolved_language=None,
            engine=engine,
            detect_table=detect_table,
            detect_layout=detect_layout,
            callback_url=callback_url,
            source_type=source_type,
            source_path=source_path,
            source_url=source_url,
            content_type=content_type,
            page_numbers=page_numbers,
        )
        with self._lock:
            self._jobs[job.job_id] = job
        return replace(job)

    def begin_processing(self, job_id: str) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status != JobStatus.pending:
                return None
            job.status = JobStatus.processing
            job.progress = 1
            return replace(job)

    def set_source(
        self,
        job_id: str,
        source_path: str,
        content_type: str,
    ) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status != JobStatus.processing:
                return None
            job.source_path = source_path
            job.content_type = content_type
            return replace(job)

    def set_progress(self, job_id: str, progress: int) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status != JobStatus.processing:
                return
            job.progress = max(0, min(100, progress))

    def complete(
        self,
        job_id: str,
        *,
        text: str,
        confidence: float,
        pages: int,
        blocks: list[OCRBlock],
        tables: list[OCRTable],
        language: str,
    ) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status != JobStatus.processing:
                return None
            job.text = text if isinstance(text, str) else ""
            job.confidence = confidence
            job.pages = pages
            job.blocks = blocks
            job.tables = tables
            job.resolved_language = language
            job.error = None
            job.progress = 100
            job.status = JobStatus.completed
            job.completed_at = utcnow()
            return replace(job)

    def fail(self, job_id: str, message: str) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status in TERMINAL_STATUSES:
                return None
            job.text = ""  # OCR failures must never expose null text
            job.status = JobStatus.failed
            job.error = message[:500]
            job.completed_at = utcnow()
            return replace(job)

    def delete(self, job_id: str) -> bool:
        with self._lock:
            removed = self._jobs.pop(job_id, None) is not None
        if removed:
            remove_job_files(job_id)
        return removed

    # ---------------------------------------------------------------- helpers

    def _apply_expiry(self, job: Job) -> None:
        """Mark long-finished jobs as expired and drop their files."""
        if job.status not in (JobStatus.completed, JobStatus.failed):
            return
        finished_at = job.completed_at or job.created_at
        if finished_at + timedelta(seconds=settings.job_ttl_seconds) > utcnow():
            return
        job.status = JobStatus.expired
        job.progress = 100
        remove_job_files(job.job_id)


store = JobStore()
