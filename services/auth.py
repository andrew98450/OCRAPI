"""Bearer token authentication (security scheme: BearerAuth)."""

from __future__ import annotations

import secrets

from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from config import settings

bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="BearerAuth",
    bearerFormat="JWT",
    description="JWT Bearer token.",
)


def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
) -> None:
    """Validate the Bearer token.

    When API_TOKEN is configured the token must match it; otherwise any
    non-empty Bearer token is accepted (development default).
    """
    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or not credentials.credentials
    ):
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    expected = settings.api_token
    if expected and not secrets.compare_digest(credentials.credentials, expected):
        raise HTTPException(
            status_code=401,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
