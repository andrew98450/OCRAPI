"""OCR endpoints: job creation, URL/Base64/PDF input, result, blocks, tables."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
)
from pydantic import HttpUrl

from config import settings
from routers.deps import get_finished_job, to_job_response, to_ocr_result
from schemas.jobs import JobResponse
from schemas.ocr import BlockResponse, OCRResult, TableResponse
from schemas.requests import OCRBase64Request, OCRUrlRequest
from services.ocr_service import process_job
from services.storage import remove_job_files, save_bytes, save_upload
from services.store import Job, new_job_id, store
from services.validators import (
    SUFFIX_BY_CONTENT_TYPE,
    ensure_signature_matches,
    require_content_type,
    validate_upload,
)

router = APIRouter(tags=["OCR"])

EngineName = Literal["paddleocr", "tesseract", "azure"]

_ENGINE_HINT = (
    "Only the tesseract engine is bundled in this deployment; other enum values "
    "are accepted and processed with Tesseract."
)

_UPLOAD_ERROR_RESPONSES = {
    400: {"description": "File missing, empty or invalid file name"},
    413: {"description": "File exceeds the 20MB size limit"},
    415: {"description": "Unsupported Content-Type"},
}

_JSON_ERROR_RESPONSES = {
    413: {"description": "File exceeds the 20MB size limit"},
    415: {"description": "Unsupported image content"},
}


def _clean_language(language: str | None) -> str | None:
    if language is None:
        return None
    cleaned = language.strip()
    return cleaned or None


def _remote_file_name(url: str) -> str:
    name = Path(urlparse(url).path).name
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip()
    return name[:255] or "remote-image"


@router.post(
    "/ocr/jobs",
    response_model=JobResponse,
    status_code=202,
    summary="Create OCR Job",
    responses={**_UPLOAD_ERROR_RESPONSES, 202: {"description": "Accepted"}},
)
async def create_ocr_job(
    background_tasks: BackgroundTasks,
    file: UploadFile | None = File(
        default=None, description="Image (JPEG/PNG/WebP) or PDF document."
    ),
    language: str | None = Form(default=None, examples=["chi_tra"]),
    engine: EngineName | None = Form(default=None, description=_ENGINE_HINT),
    detect_table: bool = Form(default=False),
    detect_layout: bool = Form(default=False),
    callback_url: HttpUrl | None = Form(default=None),
) -> JobResponse:
    file_name, content_type = validate_upload(file)
    if file is None:  # pragma: no cover - validate_upload raises first
        raise HTTPException(status_code=400, detail="File is required")

    job_id = new_job_id()
    path = await save_upload(file, job_id, SUFFIX_BY_CONTENT_TYPE[content_type])

    try:
        ensure_signature_matches(path, content_type)
    except HTTPException:
        remove_job_files(job_id)
        raise

    job = store.create(
        job_id=job_id,
        file_name=file_name,
        language=_clean_language(language),
        engine=engine or settings.default_engine,
        detect_table=detect_table,
        detect_layout=detect_layout,
        callback_url=str(callback_url) if callback_url else None,
        source_type="upload",
        source_path=str(path),
        content_type=content_type,
    )
    background_tasks.add_task(process_job, job_id)
    return to_job_response(job)


@router.post(
    "/ocr/url",
    response_model=JobResponse,
    status_code=202,
    summary="OCR From Image URL",
    responses={202: {"description": "Accepted"}},
)
def create_ocr_job_from_url(
    payload: OCRUrlRequest,
    background_tasks: BackgroundTasks,
) -> JobResponse:
    image_url = str(payload.image_url)
    job = store.create(
        file_name=_remote_file_name(image_url),
        language=_clean_language(payload.language),
        engine=settings.default_engine,
        detect_table=False,
        detect_layout=False,
        callback_url=None,
        source_type="url",
        source_url=image_url,
        content_type=None,
    )
    background_tasks.add_task(process_job, job.job_id)
    return to_job_response(job)


@router.post(
    "/ocr/base64",
    response_model=JobResponse,
    status_code=202,
    summary="OCR From Base64",
    responses={**_JSON_ERROR_RESPONSES, 202: {"description": "Accepted"}},
)
def create_ocr_job_from_base64(
    payload: OCRBase64Request,
    background_tasks: BackgroundTasks,
) -> JobResponse:
    data, content_type = payload.decoded()
    if len(data) > settings.max_file_size_bytes:
        raise HTTPException(status_code=413, detail="File exceeds the 20MB size limit")

    job_id = new_job_id()
    suffix = SUFFIX_BY_CONTENT_TYPE[content_type]
    path = save_bytes(data, job_id, suffix)

    job = store.create(
        job_id=job_id,
        file_name=f"base64_image{suffix}",
        language=_clean_language(payload.language),
        engine=settings.default_engine,
        detect_table=False,
        detect_layout=False,
        callback_url=None,
        source_type="base64",
        source_path=str(path),
        content_type=content_type,
    )
    background_tasks.add_task(process_job, job_id)
    return to_job_response(job)


@router.post(
    "/ocr/pdf",
    response_model=JobResponse,
    status_code=202,
    summary="OCR PDF",
    responses={**_UPLOAD_ERROR_RESPONSES, 202: {"description": "Accepted"}},
)
async def create_ocr_job_from_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile | None = File(default=None, description="PDF document."),
    pages: list[int] | None = Form(
        default=None,
        description="1-based page numbers to process (all pages when omitted).",
    ),
) -> JobResponse:
    file_name, content_type = validate_upload(file)
    if file is None:  # pragma: no cover - validate_upload raises first
        raise HTTPException(status_code=400, detail="File is required")
    require_content_type(
        content_type,
        frozenset({"application/pdf"}),
        detail="This endpoint only accepts application/pdf files",
    )

    page_numbers: list[int] | None = None
    if pages is not None:
        if any(page < 1 for page in pages):
            raise HTTPException(
                status_code=422, detail="pages must contain positive integers"
            )
        page_numbers = sorted(set(pages)) or None

    job_id = new_job_id()
    path = await save_upload(file, job_id, SUFFIX_BY_CONTENT_TYPE[content_type])

    try:
        ensure_signature_matches(path, content_type)
    except HTTPException:
        remove_job_files(job_id)
        raise

    job = store.create(
        job_id=job_id,
        file_name=file_name,
        language=None,
        engine=settings.default_engine,
        detect_table=False,
        detect_layout=False,
        callback_url=None,
        source_type="pdf",
        source_path=str(path),
        content_type=content_type,
        page_numbers=page_numbers,
    )
    background_tasks.add_task(process_job, job_id)
    return to_job_response(job)


@router.get(
    "/ocr/jobs/{jobId}/result",
    response_model=OCRResult,
    summary="OCR Result",
    responses={200: {"description": "OCR Result"}},
)
def get_ocr_result(job: Job = Depends(get_finished_job)) -> OCRResult:
    return to_ocr_result(job)


@router.get(
    "/ocr/jobs/{jobId}/blocks",
    response_model=BlockResponse,
    summary="OCR Blocks",
    responses={200: {"description": "OCR Blocks"}},
)
def get_ocr_blocks(job: Job = Depends(get_finished_job)) -> BlockResponse:
    return BlockResponse(job_id=job.job_id, blocks=job.blocks)


@router.get(
    "/ocr/jobs/{jobId}/tables",
    response_model=TableResponse,
    summary="OCR Tables",
    responses={200: {"description": "OCR Tables"}},
)
def get_ocr_tables(job: Job = Depends(get_finished_job)) -> TableResponse:
    return TableResponse(tables=job.tables)
