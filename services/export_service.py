"""Export builders: TXT, JSON, DOCX and searchable PDF."""

from __future__ import annotations

import io
import json
import logging

import pytesseract
from docx import Document
from pypdf import PdfReader, PdfWriter

from services.ocr_service import iter_page_images, resolve_language
from services.store import Job

logger = logging.getLogger(__name__)


def _language(job: Job) -> str:
    return job.resolved_language or resolve_language(job.language)


def _result_mapping(job: Job) -> dict:
    return {
        "job_id": job.job_id,
        "file_name": job.file_name,
        "language": _language(job),
        "confidence": job.confidence,
        "pages": job.pages,
        "text": job.text or "",
        "blocks": [block.model_dump() for block in job.blocks],
        "tables": [table.model_dump() for table in job.tables],
    }


def build_txt(job: Job) -> bytes:
    return (job.text or "").encode("utf-8")


def build_json(job: Job) -> bytes:
    payload = json.dumps(_result_mapping(job), ensure_ascii=False, indent=2)
    return payload.encode("utf-8")


def build_docx(job: Job) -> bytes:
    document = Document()
    document.add_heading(job.file_name or "OCR Result", level=1)

    for line in (job.text or "").splitlines():
        document.add_paragraph(line)

    for table in job.tables:
        column_count = max((len(row) for row in table.rows), default=0)
        if not table.rows or column_count == 0:
            continue
        doc_table = document.add_table(rows=len(table.rows), cols=column_count)
        for row_index, row in enumerate(table.rows):
            for column_index in range(column_count):
                value = row[column_index] if column_index < len(row) else ""
                doc_table.cell(row_index, column_index).text = value

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def build_searchable_pdf(job: Job) -> bytes:
    """Render each page to an image and attach an invisible OCR text layer."""
    language = _language(job)
    page_pdfs: list[bytes] = []

    for image in iter_page_images(job):
        try:
            page_pdfs.append(
                pytesseract.image_to_pdf_or_hocr(
                    image,
                    extension="pdf",
                    lang=language,
                )
            )
        finally:
            try:
                image.close()
            except Exception:  # noqa: BLE001
                pass

    if not page_pdfs:
        raise RuntimeError("The document contains no pages to export")

    if len(page_pdfs) == 1:
        return page_pdfs[0]

    writer = PdfWriter()
    for page_pdf in page_pdfs:
        writer.append(PdfReader(io.BytesIO(page_pdf)))
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()
