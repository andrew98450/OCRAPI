"""Local file storage for uploaded sources and rendered job data."""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import HTTPException, UploadFile

from config import settings

_CHUNK_SIZE = 1024 * 1024
_TOO_LARGE_DETAIL = "File exceeds the 20MB size limit"


def ensure_storage() -> None:
    settings.storage_dir.mkdir(parents=True, exist_ok=True)


def job_dir(job_id: str) -> Path:
    return settings.storage_dir / job_id


def remove_job_files(job_id: str) -> None:
    shutil.rmtree(job_dir(job_id), ignore_errors=True)


def _prepare(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


async def save_upload(upload: UploadFile, job_id: str, suffix: str) -> Path:
    """Stream an UploadFile to disk while enforcing the 20MB limit.

    Raises:
        HTTPException 413: file larger than 20MB.
        HTTPException 400: empty file.
    """
    target = _prepare(job_dir(job_id) / f"source{suffix}")
    total = 0
    try:
        with target.open("wb") as handle:
            while True:
                chunk = await upload.read(_CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > settings.max_file_size_bytes:
                    raise HTTPException(status_code=413, detail=_TOO_LARGE_DETAIL)
                handle.write(chunk)
    except HTTPException:
        remove_job_files(job_id)
        raise
    except OSError as exc:
        remove_job_files(job_id)
        raise HTTPException(status_code=500, detail="Failed to store uploaded file") from exc
    finally:
        await upload.close()

    if total == 0:
        remove_job_files(job_id)
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    return target


def save_bytes(data: bytes, job_id: str, suffix: str) -> Path:
    """Persist decoded bytes (Base64 input) enforcing the same limits."""
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    if len(data) > settings.max_file_size_bytes:
        raise HTTPException(status_code=413, detail=_TOO_LARGE_DETAIL)

    target = _prepare(job_dir(job_id) / f"source{suffix}")
    try:
        target.write_bytes(data)
    except OSError as exc:
        remove_job_files(job_id)
        raise HTTPException(status_code=500, detail="Failed to store uploaded file") from exc

    return target
