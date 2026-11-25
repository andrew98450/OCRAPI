"""Shared router dependencies and response builders."""

from __future__ import annotations

from fastapi import HTTPException

from config import settings
from schemas.jobs import JobResponse, JobStatus, JobStatusResponse, JobSummary
from schemas.ocr import OCRResult
from services.store import Job, store


def get_job(jobId: str) -> Job:  # camelCase: the path template is {jobId}
    job = store.get(jobId)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def get_finished_job(jobId: str) -> Job:  # camelCase: the path template is {jobId}
    """Job in a terminal state (completed or failed)."""
    job = get_job(jobId)
    if job.status == JobStatus.expired:
        raise HTTPException(status_code=410, detail="Job has expired")
    if job.status in (JobStatus.pending, JobStatus.processing):
        raise HTTPException(status_code=409, detail="Job is not finished yet")
    return job


def get_completed_job(jobId: str) -> Job:  # camelCase: the path template is {jobId}
    """Successfully completed job (required for exports)."""
    job = get_job(jobId)
    if job.status == JobStatus.expired:
        raise HTTPException(status_code=410, detail="Job has expired")
    if job.status == JobStatus.failed:
        raise HTTPException(
            status_code=409,
            detail="OCR job failed; no result is available for export",
        )
    if job.status != JobStatus.completed:
        raise HTTPException(status_code=409, detail="Job is not finished yet")
    return job


def to_job_response(job: Job) -> JobResponse:
    return JobResponse(
        job_id=job.job_id,
        status=job.status,
        created_at=job.created_at,
    )


def to_job_status_response(job: Job) -> JobStatusResponse:
    return JobStatusResponse(
        job_id=job.job_id,
        status=job.status,
        progress=job.progress,
        created_at=job.created_at,
        completed_at=job.completed_at,
    )


def to_job_summary(job: Job) -> JobSummary:
    return JobSummary(job_id=job.job_id, file_name=job.file_name, status=job.status)


def to_ocr_result(job: Job) -> OCRResult:
    language = job.resolved_language or job.language or settings.default_language
    return OCRResult(
        job_id=job.job_id,
        file_name=job.file_name,
        language=language,
        confidence=job.confidence,
        pages=job.pages,
        # Requirement: never null, empty string when nothing was recognized.
        text=job.text or "",
    )
