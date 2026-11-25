"""OCR processing (Pytesseract + Pillow).

The processing function is synchronous and is executed by FastAPI background
tasks in the threadpool after the 202 response has been sent.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import pytesseract
from PIL import Image, ImageOps, UnidentifiedImageError
from pytesseract import Output

from config import settings
from schemas.ocr import BoundingBox, OCRBlock, OCRTable
from services.callback import notify
from services.fetcher import download_source
from services.store import Job, store

logger = logging.getLogger(__name__)

_LANGUAGE_SEPARATOR = re.compile(r"[+,]")
_CJK_RANGE = "\u3000-\u303f\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef"
_CJK_SPACES = re.compile(rf"(?<=[{_CJK_RANGE}])\s+(?=[{_CJK_RANGE}])")
_TABLE_CELL_SEPARATOR = re.compile(r"\t+|\s{2,}|\s*\|\s*")


class OCROperationError(RuntimeError):
    """Raised when an OCR job cannot be completed."""


# --------------------------------------------------------------------- engine


def configure_tesseract() -> None:
    if settings.tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd


_available_languages: set[str] | None = None


def available_languages() -> set[str]:
    """Installed Tesseract languages (cached, excluding orientation data)."""
    global _available_languages
    if _available_languages is None:
        try:
            _available_languages = {
                language
                for language in pytesseract.get_languages(config="")
                if language != "osd"
            }
        except Exception:  # noqa: BLE001 - tesseract may be unavailable
            logger.warning(
                "Unable to list Tesseract languages; using requested values as-is"
            )
            _available_languages = set()
    return _available_languages


def resolve_language(requested: str | None) -> str:
    """Pick the requested language if installed, else a sane fallback.

    Values such as ``chi_tra+eng`` are supported; unknown parts are dropped.
    """
    available = available_languages()

    def usable(language: str | None) -> bool:
        if not language:
            return False
        return not available or language in available

    if requested:
        parts = [part.strip() for part in _LANGUAGE_SEPARATOR.split(requested) if part.strip()]
        valid = [part for part in parts if usable(part)]
        if valid:
            return "+".join(valid)
        logger.warning(
            "Requested OCR language '%s' is not installed; using fallback", requested
        )

    fallback = settings.default_language
    if usable(fallback):
        return fallback
    if "eng" in available:
        return "eng"
    if available:
        return sorted(available)[0]
    return fallback


# --------------------------------------------------------------- image loading


def _source_path(job: Job) -> Path:
    if not job.source_path:
        raise OCROperationError("Source file is missing")
    path = Path(job.source_path)
    if not path.exists():
        raise OCROperationError("Source file is no longer available")
    return path


def _pdf_page_count(path: Path) -> int:
    try:
        from pdf2image import pdfinfo_from_path
    except ImportError as exc:  # pragma: no cover - dependency is required
        raise OCROperationError("PDF support is not available") from exc

    try:
        info = pdfinfo_from_path(str(path))
        total_pages = int(info.get("Pages", 0))
    except Exception as exc:  # noqa: BLE001 - poppler errors are opaque
        raise OCROperationError("Unable to read the PDF document") from exc

    if total_pages <= 0:
        raise OCROperationError("The PDF document has no pages")
    return total_pages


def _selected_pdf_pages(total_pages: int, pages: list[int] | None) -> list[int]:
    if pages:
        selected = sorted({page for page in pages if 1 <= page <= total_pages})
        if not selected:
            raise OCROperationError("None of the requested pages exist in the PDF")
    else:
        selected = list(range(1, total_pages + 1))

    if len(selected) > settings.max_pdf_pages:
        raise OCROperationError(
            f"PDF exceeds the maximum of {settings.max_pdf_pages} pages"
        )
    return selected


def _render_pdf_page(path: Path, page_number: int) -> list[Image.Image]:
    try:
        from pdf2image import convert_from_path
    except ImportError as exc:  # pragma: no cover - dependency is required
        raise OCROperationError("PDF support is not available") from exc

    try:
        images = convert_from_path(
            str(path),
            dpi=settings.pdf_dpi,
            first_page=page_number,
            last_page=page_number,
        )
    except Exception as exc:  # noqa: BLE001 - poppler errors are opaque
        raise OCROperationError(
            f"Unable to render page {page_number} of the PDF"
        ) from exc

    if not images:
        raise OCROperationError(f"Unable to render page {page_number} of the PDF")
    return images


def count_pages(job: Job) -> int:
    """Number of pages that will be processed (without rendering them)."""
    path = _source_path(job)
    if job.content_type == "application/pdf":
        return len(_selected_pdf_pages(_pdf_page_count(path), job.page_numbers))
    return 1


def iter_page_images(job: Job):
    """Yield RGB page images one at a time so memory stays bounded.

    The caller owns each image and must close it after use.
    """
    path = _source_path(job)

    if job.content_type == "application/pdf":
        total_pages = _pdf_page_count(path)
        for page_number in _selected_pdf_pages(total_pages, job.page_numbers):
            for image in _render_pdf_page(path, page_number):
                try:
                    yield image.convert("RGB")
                finally:
                    image.close()
        return

    try:
        with Image.open(path) as image:
            image.load()
            yield ImageOps.exif_transpose(image).convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise OCROperationError("Unable to read the uploaded image") from exc


# ------------------------------------------------------------------ per page


@dataclass
class _LineGroup:
    block_num: int
    words: list[str] = field(default_factory=list)
    confidences: list[float] = field(default_factory=list)
    left: int = 0
    top: int = 0
    right: int = 0
    bottom: int = 0


@dataclass
class PageOCR:
    text: str
    blocks: list[OCRBlock]
    word_confidences: list[float]


def _normalise_line(text: str) -> str:
    collapsed = re.sub(r"\s+", " ", text).strip()
    return _CJK_SPACES.sub("", collapsed).strip()


def _bbox(left: int, top: int, right: int, bottom: int) -> BoundingBox:
    return BoundingBox(
        x=int(left),
        y=int(top),
        width=max(int(right) - int(left), 0),
        height=max(int(bottom) - int(top), 0),
    )


def _ocr_page(image: Image.Image, language: str, detect_layout: bool) -> PageOCR:
    """Run Tesseract once and derive text, blocks and confidences."""
    data = pytesseract.image_to_data(image, lang=language, output_type=Output.DICT)

    texts = data.get("text") or []
    groups: dict[tuple[int, int, int], _LineGroup] = {}
    order: list[tuple[int, int, int]] = []
    word_confidences: list[float] = []

    for index in range(len(texts)):
        word = (texts[index] or "").strip()
        if not word:
            continue
        try:
            confidence = float(data["conf"][index])
        except (KeyError, TypeError, ValueError):
            confidence = -1.0
        if confidence < 0:
            continue
        try:
            left = int(data["left"][index])
            top = int(data["top"][index])
            width = int(data["width"][index])
            height = int(data["height"][index])
            key = (
                int(data["block_num"][index]),
                int(data["par_num"][index]),
                int(data["line_num"][index]),
            )
        except (KeyError, TypeError, ValueError):
            continue
        if width <= 0 or height <= 0:
            continue

        group = groups.get(key)
        if group is None:
            group = _LineGroup(
                block_num=key[0],
                left=left,
                top=top,
                right=left + width,
                bottom=top + height,
            )
            groups[key] = group
            order.append(key)
        else:
            group.left = min(group.left, left)
            group.top = min(group.top, top)
            group.right = max(group.right, left + width)
            group.bottom = max(group.bottom, top + height)

        group.words.append(word)
        group.confidences.append(confidence)
        word_confidences.append(confidence)

    entries: list[dict] = []
    for key in order:
        group = groups[key]
        text = _normalise_line(" ".join(group.words))
        if not text:
            continue
        entries.append(
            {
                "block": group.block_num,
                "text": text,
                "confidence": sum(group.confidences) / len(group.confidences),
                "left": group.left,
                "top": group.top,
                "right": group.right,
                "bottom": group.bottom,
            }
        )

    blocks: list[OCRBlock]
    if detect_layout and entries:
        merged: list[dict] = []
        for entry in entries:
            if merged and merged[-1]["block"] == entry["block"]:
                current = merged[-1]
                current["texts"].append(entry["text"])
                current["confidences"].append(entry["confidence"])
                current["left"] = min(current["left"], entry["left"])
                current["top"] = min(current["top"], entry["top"])
                current["right"] = max(current["right"], entry["right"])
                current["bottom"] = max(current["bottom"], entry["bottom"])
            else:
                merged.append(
                    {
                        "block": entry["block"],
                        "texts": [entry["text"]],
                        "confidences": [entry["confidence"]],
                        "left": entry["left"],
                        "top": entry["top"],
                        "right": entry["right"],
                        "bottom": entry["bottom"],
                    }
                )
        blocks = [
            OCRBlock(
                text="\n".join(block["texts"]),
                confidence=round(
                    sum(block["confidences"]) / len(block["confidences"]), 2
                ),
                bbox=_bbox(
                    block["left"], block["top"], block["right"], block["bottom"]
                ),
            )
            for block in merged
        ]
    else:
        blocks = [
            OCRBlock(
                text=entry["text"],
                confidence=round(entry["confidence"], 2),
                bbox=_bbox(
                    entry["left"], entry["top"], entry["right"], entry["bottom"]
                ),
            )
            for entry in entries
        ]

    page_text = "\n".join(entry["text"] for entry in entries)
    return PageOCR(text=page_text, blocks=blocks, word_confidences=word_confidences)


# -------------------------------------------------------------------- tables


def extract_tables(text: str, first_table_id: int) -> list[OCRTable]:
    """Detect simple column-aligned tables in OCR text.

    Rows are recognised by tab stops, runs of two or more spaces, or pipe
    separators. Only blocks with at least two rows are reported.
    """
    tables: list[OCRTable] = []
    rows: list[list[str]] = []
    next_id = first_table_id

    def flush() -> None:
        nonlocal rows, next_id
        if len(rows) >= 2:
            tables.append(OCRTable(table_id=next_id, rows=[row[:] for row in rows]))
            next_id += 1
        rows = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            flush()
            continue
        cells = [cell.strip() for cell in _TABLE_CELL_SEPARATOR.split(line)]
        cells = [cell for cell in cells if cell]
        if len(cells) < 2:
            flush()
            continue
        rows.append(cells)
    flush()

    return tables


# ------------------------------------------------------------------- pipeline


def _error_message(exc: Exception) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    return message.splitlines()[0][:500]


def _callback_payload(job: Job) -> dict:
    return {
        "job_id": job.job_id,
        "status": job.status.value,
        "progress": job.progress,
        "created_at": job.created_at.isoformat(),
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "error": job.error,
    }


def _run(job: Job) -> Job | None:
    if job.source_type == "url":
        if not job.source_url:
            raise OCROperationError("Source URL is missing")
        path, content_type = download_source(job.source_url, job.job_id)
        job = store.set_source(job.job_id, str(path), content_type) or job

    language = resolve_language(job.language)
    store.set_progress(job.job_id, 5)

    total_pages = count_pages(job)
    page_texts: list[str] = []
    blocks: list[OCRBlock] = []
    tables: list[OCRTable] = []
    word_confidences: list[float] = []
    next_table_id = 1

    for index, image in enumerate(iter_page_images(job), start=1):
        try:
            page = _ocr_page(image, language, job.detect_layout)
        finally:
            try:
                image.close()
            except Exception:  # noqa: BLE001 - closing must never fail a job
                pass

        page_texts.append(page.text)
        blocks.extend(page.blocks)
        word_confidences.extend(page.word_confidences)

        if job.detect_table:
            extracted = extract_tables(page.text, next_table_id)
            tables.extend(extracted)
            next_table_id += len(extracted)

        store.set_progress(job.job_id, 5 + int(90 * index / max(total_pages, 1)))

    # Requirement: OCR text is never null; empty string on empty output.
    text = "\n\n".join(page_texts).strip("\n")
    confidence = (
        round(sum(word_confidences) / len(word_confidences), 2)
        if word_confidences
        else 0.0
    )

    return store.complete(
        job.job_id,
        text=text,
        confidence=confidence,
        pages=total_pages,
        blocks=blocks,
        tables=tables,
        language=language,
    )


def process_job(job_id: str) -> None:
    """Background task entry point: run OCR and notify the callback URL."""
    job = store.begin_processing(job_id)
    if job is None:
        return

    finished: Job | None
    try:
        finished = _run(job)
    except Exception as exc:  # noqa: BLE001 - job failures are reported by status
        logger.exception("OCR job %s failed", job_id)
        finished = store.fail(job_id, _error_message(exc))

    if finished is not None:
        notify(finished.callback_url, _callback_payload(finished))


__all__ = [
    "OCROperationError",
    "available_languages",
    "configure_tesseract",
    "count_pages",
    "extract_tables",
    "iter_page_images",
    "process_job",
    "resolve_language",
]
