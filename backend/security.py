"""Security helpers for internal/service-to-service endpoints.

Endpoints under /api/internal/* are NOT meant to be called by the mobile app
or by end users — only by our own scheduler (in-process) or, as a manual
fallback, by an operator holding INTERNAL_SERVICE_TOKEN. They must never be
reachable without this guard.
"""

from __future__ import annotations

import hmac
import os

from fastapi import Header, HTTPException

_SERVICE_TOKEN = os.environ.get("INTERNAL_SERVICE_TOKEN", "")

if not _SERVICE_TOKEN:
    # Fail loudly at import time rather than silently accepting any caller.
    # In production this must come from the secrets manager, never a default.
    raise RuntimeError(
        "INTERNAL_SERVICE_TOKEN não configurado. Defina uma string aleatória "
        "longa (ex: `openssl rand -hex 32`) no .env antes de subir o servidor."
    )


async def require_service_token(
    x_internal_token: str | None = Header(default=None, alias="X-Internal-Token"),
) -> None:
    """Guards /api/internal/* routes. Uses constant-time comparison to avoid
    leaking the token via response-time side channels."""
    if not x_internal_token or not hmac.compare_digest(x_internal_token, _SERVICE_TOKEN):
        raise HTTPException(401, "Token de serviço inválido ou ausente")
