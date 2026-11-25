"""Runtime configuration for the OCR Recognition Service.

All values are read from environment variables so the same image can run in
different environments without code changes.
"""

from __future__ import annotations

import os
from pathlib import Path

# Hard limit required by the API specification (single file: 20MB).
MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


class Settings:
    """Application settings."""

    def __init__(self) -> None:
        self.storage_dir: Path = self._resolve_storage_dir(
            os.getenv("STORAGE_DIR", "storage")
        )

        self.max_file_size_bytes: int = MAX_FILE_SIZE_BYTES
        self.max_pdf_pages: int = _int_env("MAX_PDF_PAGES", 100)
        self.pdf_dpi: int = _int_env("PDF_DPI", 200)
        self.job_ttl_seconds: int = _int_env("JOB_TTL_SECONDS", 24 * 60 * 60)

        self.default_language: str = os.getenv("DEFAULT_OCR_LANGUAGE", "eng").strip() or "eng"
        self.default_engine: str = os.getenv("DEFAULT_OCR_ENGINE", "tesseract").strip() or "tesseract"
        self.tesseract_cmd: str | None = os.getenv("TESSERACT_CMD") or None
        self.http_timeout_seconds: int = _int_env("HTTP_TIMEOUT_SECONDS", 60)

    @staticmethod
    def _resolve_storage_dir(raw: str) -> Path:
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        return path.resolve()


settings = Settings()
