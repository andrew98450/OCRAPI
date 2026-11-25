"""Job management endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from routers.deps import get_job, to_job_status_response, to_job_summary
from schemas.jobs import JobListResponse, JobStatus, JobStatusResponse
from services.auth import require_auth
from services.store import Job, store

router = APIRouter(tags=["Jobs"], dependencies=[Depends(require_auth)])


@router.get(
    "/ocr/jobs",
    response_model=JobListResponse,
    summary="List OCR Jobs",
    responses={200: {"description": "Success"}},
)
def list_ocr_jobs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1),
    status: JobStatus | None = Query(default=None),
) -> JobListResponse:
    total, jobs = store.list(page=page, page_size=page_size, status=status)
    return JobListResponse(
        total=total,
        page=page,
        data=[to_job_summary(job) for job in jobs],
    )


@router.get(
    "/ocr/jobs/{jobId}",
    response_model=JobStatusResponse,
    summary="Get Job Status",
    responses={200: {"description": "Success"}},
)
def get_job_status(
    job: Job = Depends(get_job),
) -> JobStatusResponse:
    return to_job_status_response(job)


@router.delete(
    "/ocr/jobs/{jobId}",
    summary="Delete Job",
    responses={200: {"description": "Deleted"}},
)
def delete_ocr_job(jobId: str) -> dict[str, object]:  # noqa: N803 - path parameter
    if not store.delete(jobId):
        raise HTTPException(status_code=404, detail="Job not found")
    return {"job_id": jobId, "deleted": True}
