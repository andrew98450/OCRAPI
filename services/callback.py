"""Completion callbacks for jobs created with ``callback_url``."""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def notify(url: str | None, payload: dict[str, Any]) -> None:
    """POST the job state to ``url``. Failures are logged, never raised."""
    if not url:
        return
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(url, json=payload)
        if response.status_code >= 400:
            logger.warning(
                "Callback to %s returned HTTP %s", url, response.status_code
            )
    except Exception:  # noqa: BLE001 - callbacks must never break a job
        logger.warning("Callback to %s failed", url, exc_info=True)
