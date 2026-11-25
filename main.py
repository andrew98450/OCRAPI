"""OCR Recognition Service API - FastAPI application entrypoint.

Implements the contract described in openapi.yaml:
    POST   /ocr/jobs
    GET    /ocr/jobs
    POST   /ocr/url
    POST   /ocr/base64
    POST   /ocr/pdf
    GET    /ocr/jobs/{jobId}
    DELETE /ocr/jobs/{jobId}
    GET    /ocr/jobs/{jobId}/result
    GET    /ocr/jobs/{jobId}/blocks
    GET    /ocr/jobs/{jobId}/tables
    GET    /ocr/jobs/{jobId}/export/txt
    GET    /ocr/jobs/{jobId}/export/json
    GET    /ocr/jobs/{jobId}/export/docx
    GET    /ocr/jobs/{jobId}/export/pdf
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from config import settings
from routers import export as export_router
from routers import jobs as jobs_router
from routers import ocr as ocr_router
from services.ocr_service import configure_tesseract
from services.storage import ensure_storage

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("ocr.api")

DESCRIPTION = """OCR RESTful Service

Features:
  - Image OCR
  - PDF OCR
  - URL OCR
  - Base64 OCR
  - Layout Analysis
  - Table Extraction
  - Async Processing
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_storage()
    configure_tesseract()
    logger.info("OCR service ready (storage=%s)", settings.storage_dir)
    yield


app = FastAPI(
    title="OCR Recognition Service API",
    version="1.0.0",
    description=DESCRIPTION,
    lifespan=lifespan,
)

app.include_router(ocr_router.router)
app.include_router(jobs_router.router)
app.include_router(export_router.router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
    )
