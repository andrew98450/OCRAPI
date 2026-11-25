"""Download of remote images for POST /ocr/url."""

from __future__ import annotations

from pathlib import Path

import httpx

from config import settings
from services.storage import job_dir
from services.validators import (
    IMAGE_CONTENT_TYPES,
    SUFFIX_BY_CONTENT_TYPE,
    normalize_content_type,
    sniff_content_type,
)


class SourceFetchError(RuntimeError):
    """Raised when a remote source cannot be used for OCR."""


def download_source(url: str, job_id: str) -> tuple[Path, str]:
    """Download ``url`` into the job directory and validate it.

    Returns:
        tuple of (stored path, content type)

    Raises:
        SourceFetchError: download failed, unsupported type, empty or too large.
    """
    max_bytes = settings.max_file_size_bytes
    target: Path | None = None

    try:
        timeout = httpx.Timeout(settings.http_timeout_seconds, connect=10.0)
        with httpx.Client(follow_redirects=True, timeout=timeout) as client:
            with client.stream(
                "GET",
                url,
                headers={"Accept": "image/jpeg, image/png, image/webp"},
            ) as response:
                if response.status_code >= 400:
                    raise SourceFetchError(
                        f"Source URL returned HTTP {response.status_code}"
                    )

                content_type = normalize_content_type(
                    response.headers.get("content-type")
                )
                if content_type not in IMAGE_CONTENT_TYPES:
                    raise SourceFetchError(
                        "Unsupported source Content-Type: "
                        f"{content_type or 'unknown'}"
                    )

                declared_length = response.headers.get("content-length")
                if declared_length and declared_length.isdigit():
                    if int(declared_length) > max_bytes:
                        raise SourceFetchError("Source file exceeds the 20MB size limit")

                directory = job_dir(job_id)
                directory.mkdir(parents=True, exist_ok=True)
                target = directory / f"source{SUFFIX_BY_CONTENT_TYPE[content_type]}"

                total = 0
                with target.open("wb") as handle:
                    for chunk in response.iter_bytes(1024 * 1024):
                        total += len(chunk)
                        if total > max_bytes:
                            raise SourceFetchError(
                                "Source file exceeds the 20MB size limit"
                            )
                        handle.write(chunk)

        if total == 0:
            raise SourceFetchError("Source file is empty")

        with target.open("rb") as handle:
            detected = sniff_content_type(handle.read(16))
        if detected != content_type:
            raise SourceFetchError(
                "Source content does not match its declared Content-Type"
            )

        return target, content_type
    except SourceFetchError:
        if target is not None:
            target.unlink(missing_ok=True)
        raise
    except httpx.HTTPError as exc:
        if target is not None:
            target.unlink(missing_ok=True)
        raise SourceFetchError(f"Failed to download source: {exc}") from exc
    except OSError as exc:
        if target is not None:
            target.unlink(missing_ok=True)
        raise SourceFetchError("Failed to store the downloaded source") from exc
