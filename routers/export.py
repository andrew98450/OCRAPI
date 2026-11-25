"""Export endpoints (TXT, JSON, DOCX, searchable PDF)."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, Response

from routers.deps import get_completed_job
from services.auth import require_auth
from services.export_service import (
    build_docx,
    build_json,
    build_searchable_pdf,
    build_txt,
)
from services.store import Job

router = APIRouter(tags=["Export"], dependencies=[Depends(require_auth)])

TXT_MEDIA_TYPE = "text/plain; charset=utf-8"
JSON_MEDIA_TYPE = "application/json"
DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
PDF_MEDIA_TYPE = "application/pdf"


def _export_file_name(job: Job, extension: str) -> str:
    stem = Path(job.file_name or "ocr-result").stem
    stem = re.sub(r'[\x00-\x1f\x7f"\\/]', "_", stem).strip() or "ocr-result"
    return f"{stem[:100]}{extension}"


def _attachment_headers(job: Job, extension: str) -> dict[str, str]:
    filename = _export_file_name(job, extension)
    ascii_name = filename.encode("ascii", "ignore").decode() or f"ocr-result{extension}"
    return {
        "Content-Disposition": (
            f'attachment; filename="{ascii_name}"; '
            f"filename*=UTF-8''{quote(filename)}"
        )
    }


def _download(
    job: Job,
    content: bytes,
    media_type: str,
    extension: str,
) -> Response:
    return Response(
        content=content,
        media_type=media_type,
        headers=_attachment_headers(job, extension),
    )


@router.get(
    "/ocr/jobs/{jobId}/export/txt",
    summary="Export TXT",
    responses={200: {"description": "txt file", "content": {TXT_MEDIA_TYPE: {}}}},
)
def export_txt(job: Job = Depends(get_completed_job)) -> Response:
    return _download(job, build_txt(job), TXT_MEDIA_TYPE, ".txt")


@router.get(
    "/ocr/jobs/{jobId}/export/json",
    summary="Export JSON",
    responses={200: {"description": "json file", "content": {JSON_MEDIA_TYPE: {}}}},
)
def export_json(job: Job = Depends(get_completed_job)) -> Response:
    return _download(job, build_json(job), JSON_MEDIA_TYPE, ".json")


@router.get(
    "/ocr/jobs/{jobId}/export/docx",
    summary="Export DOCX",
    responses={200: {"description": "docx file", "content": {DOCX_MEDIA_TYPE: {}}}},
)
def export_docx(job: Job = Depends(get_completed_job)) -> Response:
    return _download(job, build_docx(job), DOCX_MEDIA_TYPE, ".docx")


@router.get(
    "/ocr/jobs/{jobId}/export/pdf",
    summary="Export Searchable PDF",
    responses={200: {"description": "pdf file", "content": {PDF_MEDIA_TYPE: {}}}},
)
def export_pdf(job: Job = Depends(get_completed_job)) -> Response:
    return _download(job, build_searchable_pdf(job), PDF_MEDIA_TYPE, ".pdf")
