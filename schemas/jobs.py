"""Job related schemas (mirrors components/schemas of openapi.yaml)."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class JobStatus(str, Enum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"
    expired = "expired"


class JobResponse(BaseModel):
    job_id: str
    status: JobStatus
    created_at: datetime


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    progress: int
    created_at: datetime
    completed_at: datetime | None = None


class JobSummary(BaseModel):
    job_id: str
    file_name: str
    status: JobStatus


class JobListResponse(BaseModel):
    total: int
    page: int
    data: list[JobSummary]
