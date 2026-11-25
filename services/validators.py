"""Input validation helpers for uploads and remote sources."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

from fastapi import HTTPException, UploadFile

ALLOWED_CONTENT_TYPES = frozenset(
    {
        "image/jpeg",
        "image/png",
        "image/webp",
        "application/pdf",
    }
)

IMAGE_CONTENT_TYPES = frozenset(
    {
        "image/jpeg",
        "image/png",
        "image/webp",
    }
)

SUFFIX_BY_CONTENT_TYPE = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "application/pdf": ".pdf",
}

# Control characters (including NUL, CR/LF) are never valid in a file name.
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def normalize_content_type(raw: str | None) -> str:
    """Return a lowercase media type without parameters."""
    if not raw:
        return ""
    return raw.split(";", 1)[0].strip().lower()


def sniff_content_type(header: bytes) -> str | None:
    """Detect the media type from the magic bytes of a file."""
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "image/webp"
    if header.startswith(b"%PDF-"):
        return "application/pdf"
    return None


def sniff_file_content_type(path: Path) -> str | None:
    """Read the first bytes of a stored file and detect its media type."""
    try:
        with path.open("rb") as handle:
            return sniff_content_type(handle.read(16))
    except OSError:
        return None


def validate_upload(upload: UploadFile | None) -> tuple[str, str]:
    """Validate an uploaded file's presence, name and declared Content-Type.

    Returns:
        tuple of (file name, normalized content type)

    Raises:
        HTTPException 400: file missing, empty name or control characters.
        HTTPException 415: unsupported Content-Type.
    """
    if upload is None:
        raise HTTPException(
            status_code=400,
            detail="File is required. Send it as multipart/form-data field 'file'.",
        )

    raw_name = upload.filename or ""
    if not raw_name.strip():
        raise HTTPException(status_code=400, detail="File name must not be empty")
    # Multipart parsers may percent-encode control characters, so decode first.
    decoded_name = unquote(raw_name)
    if _CONTROL_CHARS.search(raw_name) or _CONTROL_CHARS.search(decoded_name):
        raise HTTPException(
            status_code=400,
            detail="File name must not contain control characters",
        )

    content_type = normalize_content_type(upload.content_type)
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=415,
            detail=(
                "Unsupported Content-Type. Allowed: image/jpeg, image/png, "
                "image/webp, application/pdf"
            ),
        )

    return raw_name, content_type


def require_content_type(
    content_type: str,
    allowed: frozenset[str],
    *,
    detail: str,
) -> None:
    """Ensure an already validated media type is one of ``allowed``."""
    if content_type not in allowed:
        raise HTTPException(status_code=415, detail=detail)


def ensure_signature_matches(path: Path, declared: str) -> None:
    """Ensure the stored bytes actually match the declared Content-Type."""
    detected = sniff_file_content_type(path)
    if detected is None:
        raise HTTPException(
            status_code=415,
            detail="Unsupported or unrecognized file content",
        )
    if detected != declared:
        raise HTTPException(
            status_code=415,
            detail="File content does not match the declared Content-Type",
        )
