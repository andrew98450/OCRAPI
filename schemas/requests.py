"""Pydantic v2 request bodies for the JSON OCR endpoints."""

from __future__ import annotations

import base64
import binascii
import re

from pydantic import BaseModel, Field, HttpUrl, PrivateAttr, field_validator, model_validator

from services.validators import IMAGE_CONTENT_TYPES, sniff_content_type

_DATA_URL_PREFIX = re.compile(r"^data:[^;,]+;base64,", re.IGNORECASE)
_WHITESPACE = re.compile(r"\s+")


class OCRUrlRequest(BaseModel):
    """Body of POST /ocr/url."""

    image_url: HttpUrl
    language: str | None = None


class OCRBase64Request(BaseModel):
    """Body of POST /ocr/base64.

    The Base64 payload is validated (encoding and image signature) while the
    model is built so a malformed value results in HTTP 422. The decoded
    bytes are kept in private attributes and never serialized.
    """

    image_base64: str = Field(min_length=1)
    language: str | None = None

    _image_bytes: bytes = PrivateAttr(default=b"")
    _content_type: str = PrivateAttr(default="")

    @field_validator("image_base64")
    @classmethod
    def _validate_encoding(cls, value: str) -> str:
        cleaned = _DATA_URL_PREFIX.sub("", value.strip())
        cleaned = _WHITESPACE.sub("", cleaned)
        try:
            base64.b64decode(cleaned, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("image_base64 must be a valid Base64 encoded image") from exc
        return cleaned

    @model_validator(mode="after")
    def _decode_payload(self) -> "OCRBase64Request":
        data = base64.b64decode(self.image_base64, validate=True)
        if not data:
            raise ValueError("image_base64 must not be empty")
        detected = sniff_content_type(data[:16])
        if detected not in IMAGE_CONTENT_TYPES:
            raise ValueError(
                "image_base64 must contain a JPEG, PNG or WebP image"
            )
        self._image_bytes = data
        self._content_type = detected
        return self

    def decoded(self) -> tuple[bytes, str]:
        """Return the decoded bytes together with their detected content type."""
        return self._image_bytes, self._content_type
