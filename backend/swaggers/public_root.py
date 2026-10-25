"""Where the API documentation says the NL2SQL API lives.

The service is mounted at /nl2sql/api. On the hosted product the same routes are also
the canonical public API root, https://futuresmart.ai/database-agent/api, which the
futuresmart.ai web server forwards here. PUBLIC_API_ROOT names that root so the
OpenAPI document's "Try it out" calls it; unset (self-hosted, local) the document keeps
the mount path, as before.

FastAPI's default docs page builds absolute /nl2sql/api URLs from the mount, which break
when the page is reached through the public root, so the docs app turns it off and serves
`swagger_page`, which loads the schema by a relative URL.
"""
import os
from typing import Any, Dict, List, Optional

from fastapi.openapi.docs import get_swagger_ui_html


def openapi_servers() -> Optional[List[Dict[str, str]]]:
    root = (os.getenv("PUBLIC_API_ROOT") or "").strip().rstrip("/")
    return [{"url": root}] if root else None


def docs_app_settings() -> Dict[str, Any]:
    """FastAPI(...) arguments for a docs app that works under either root."""
    servers = openapi_servers()
    return {"docs_url": None, "servers": servers, "root_path_in_servers": servers is None}


def swagger_page(title: str):
    # Relative, so the page works at /nl2sql/api/docs and at the public root's /docs
    return get_swagger_ui_html(openapi_url="openapi.json", title=title)
