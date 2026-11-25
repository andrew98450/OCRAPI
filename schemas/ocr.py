"""OCR result schemas (mirrors components/schemas of openapi.yaml)."""

from __future__ import annotations

from pydantic import BaseModel


class OCRResult(BaseModel):
    job_id: str
    file_name: str
    language: str
    confidence: float
    pages: int
    text: str


class BoundingBox(BaseModel):
    x: int
    y: int
    width: int
    height: int


class OCRBlock(BaseModel):
    text: str
    confidence: float
    bbox: BoundingBox


class BlockResponse(BaseModel):
    job_id: str
    blocks: list[OCRBlock]


class OCRTable(BaseModel):
    table_id: int
    rows: list[list[str]]


class TableResponse(BaseModel):
    tables: list[OCRTable]
