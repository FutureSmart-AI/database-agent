"""Auth dependency for the internal (service-to-service) reports endpoints.

The public endpoints reuse NL2SQL's normal stack (`get_api_key_or_session` +
`require_agent_permission`). The internal ones cannot: they are called by a background worker
that has no browser session and no per-agent key, and they must never be reachable from a
browser — so they require the master key and deliberately do NOT fall back to session auth.
"""
import os
from typing import Optional

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_internal_service(
    api_key: Optional[str] = Security(_api_key_header),
) -> dict:
    """Accept only the master key (FASTAPI_SECRET_KEY); reject everything else.

    The key is read per call rather than captured at import so a rotated value takes effect
    without a redeploy, matching `chatbot_management.utils.api_validation`.
    """
    expected = os.getenv("FASTAPI_SECRET_KEY")
    if api_key and expected:
        # Defensive: a proxy can collapse repeated headers into one comma-separated value.
        for key in api_key.split(","):
            if key.strip() == expected:
                return {"auth_type": "internal_service"}

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid internal service credentials",
    )
