"""Construct :class:`qdrant_client.AsyncQdrantClient` with defaults that reduce log noise."""
from __future__ import annotations

import warnings
from typing import Optional

from qdrant_client import AsyncQdrantClient


def make_async_qdrant_client(
    *,
    url: str,
    api_key: Optional[str],
    timeout: int = 60,
) -> AsyncQdrantClient:
    """
    Async Qdrant client with compatibility check disabled (client 1.15.x vs server 1.13.x is common).

    When ``qdrant_url`` is ``http://...`` and an API key is set, Qdrant emits a UserWarning about
    sending the key in the clear; we filter only that message. Prefer ``https://`` in production.
    """
    base: dict = {"url": url, "api_key": api_key, "timeout": timeout}
    kwargs = {**base, "check_compatibility": False}
    url_lower = (url or "").strip().lower()
    insecure_http_key = bool(api_key and url_lower.startswith("http://"))

    def _build() -> AsyncQdrantClient:
        try:
            return AsyncQdrantClient(**kwargs)
        except TypeError:
            # Older qdrant-client without check_compatibility
            return AsyncQdrantClient(**base)

    if insecure_http_key:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="Api key is used with an insecure connection.",
                category=UserWarning,
            )
            return _build()
    return _build()
