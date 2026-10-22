"""Public-agent gate for NL2SQL.

Lets the embedded widget and the full-screen share link read a small, whitelisted set of data
anonymously — but only when the agent has opted in on that surface and the caller's Origin matches
that surface's allowlist.

The dashboard service answers the same question by asking the chat service. NL2SQL cannot: the chat
service 404s on any agent created through `POST /v1/agents`, which is the same dependency that made
`require_agent_permission` unusable. So the policy lives on `chatbot_details` here and is read
directly.

The two surfaces are independent policies, selected per-request, never combined or intersected:

    widget       -> is_public            + allowed_domains
    full_screen  -> fullscreen_is_public + fullscreen_allowed_domains

Exported helpers are called manually from handlers rather than via Depends, because a public route
must first try normal authentication and only fall back to this.
"""
from __future__ import annotations

import time
from typing import Optional
from urllib.parse import urlparse

from fastapi import HTTPException, Request, status

from logger import logger

_CACHE_TTL_SECONDS = 30.0
_cache: dict[str, tuple[float, dict]] = {}

_CLOSED = {
    "is_public": False,
    "allowed_domains": [],
    "fullscreen_is_public": False,
    "fullscreen_allowed_domains": [],
}


def extract_caller_origin(request: Request) -> Optional[str]:
    """The caller's bare lowercased hostname from Origin, falling back to Referer.

    Deliberately does NOT fall back to Host or X-Forwarded-Host: those describe where the request
    was sent (this service), not where it came from, and trusting them would defeat the allowlist.
    """
    try:
        for header in ("origin", "referer"):
            value = request.headers.get(header) or ""
            if value:
                host = (urlparse(value).hostname or "").lower()
                if host:
                    return host
    except Exception:
        return None
    return None


def host_matches_allowlist(host: str, allowed: Optional[list]) -> bool:
    """An empty allowlist means "any origin". `*` and `*.example.com` are supported."""
    if not host:
        return False
    if not allowed:
        return True

    host = host.lower()
    for entry in allowed:
        if not entry:
            continue
        rule = str(entry).strip().lower()
        if rule == "*" or rule == host:
            return True
        if rule.startswith("*."):
            suffix = rule[1:]  # ".example.com"
            if host.endswith(suffix) and host != suffix[1:]:
                return True
    return False


def _normalize_mode(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    value = str(raw).strip().lower().replace("-", "_")
    if value in ("full_screen", "fullscreen"):
        return "full_screen"
    if value == "widget":
        return "widget"
    return None


def _is_truthy(raw: Optional[str]) -> bool:
    return bool(raw) and str(raw).strip().lower() in ("true", "1", "yes", "y")


def resolve_surface(request: Request) -> str:
    """Which surface this call is for: "widget" (default) or "full_screen".

    `from_full_screen=true` is what the live widget page sends; `mode=full_screen` is accepted too,
    for parity with the chat service's contract. No signal at all means "widget", so embeds that
    predate the distinction keep working.
    """
    if _is_truthy(request.query_params.get("from_full_screen")):
        return "full_screen"
    return _normalize_mode(request.query_params.get("mode")) or "widget"


def clear_public_config_cache(agent_id: Optional[str] = None) -> None:
    """Drop cached policy so a settings change takes effect immediately rather than in ≤30s."""
    if agent_id is None:
        _cache.clear()
    else:
        _cache.pop(agent_id, None)


async def get_agent_public_config(agent_id: str) -> dict:
    """The agent's public-access policy, cached per agent for 30s.

    An unknown agent is cached as closed on both surfaces, so a typo or a probe cannot turn into a
    database query per request.
    """
    now = time.monotonic()
    cached = _cache.get(agent_id)
    if cached and cached[0] > now:
        return cached[1]

    from models.sql_models import ChatbotDetails
    from agent.services.sqlmodel_session import get_async_session
    from sqlmodel import select, or_

    try:
        async for session in get_async_session():
            result = await session.execute(
                select(ChatbotDetails).where(
                    or_(ChatbotDetails.agent_id == agent_id, ChatbotDetails.chatbot_id == agent_id)
                )
            )
            agent = result.scalars().first()
    except Exception as e:
        # Never fail open: a database problem must not make a private agent readable.
        logger.error(f"[public-gate] policy lookup failed for {agent_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to verify agent public-access config",
        )

    if agent is None or getattr(agent, "deleted", False):
        cfg = dict(_CLOSED)
    else:
        cfg = {
            "is_public": bool(getattr(agent, "is_public", False)),
            "allowed_domains": list(getattr(agent, "allowed_domains", None) or []),
            "fullscreen_is_public": bool(getattr(agent, "fullscreen_is_public", False)),
            "fullscreen_allowed_domains": list(
                getattr(agent, "fullscreen_allowed_domains", None) or []
            ),
        }

    _cache[agent_id] = (now + _CACHE_TTL_SECONDS, cfg)
    return cfg


async def require_public_agent(request: Request, agent_id: str) -> dict:
    """Gate an anonymous request against the agent's policy for the requested surface.

    401 when that surface is not public, 403 when its allowlist is set and the caller's
    Origin/Referer does not match. Returns an auth context tagged `auth_type=public`.
    """
    cfg = await get_agent_public_config(agent_id)
    surface = resolve_surface(request)

    if surface == "full_screen":
        surface_is_public = cfg.get("fullscreen_is_public", False)
        allowed = cfg.get("fullscreen_allowed_domains") or []
    else:
        surface_is_public = cfg.get("is_public", False)
        allowed = cfg.get("allowed_domains") or []

    if not surface_is_public:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Agent is not publicly accessible",
        )

    if allowed:
        origin = extract_caller_origin(request)
        if not origin:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing Origin/Referer")
        if not host_matches_allowlist(origin, allowed):
            logger.info(
                f"[public-gate] origin '{origin}' rejected for agent {agent_id} "
                f"(surface={surface}); allowed={allowed}"
            )
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Origin not permitted")

    return {"auth_type": "public", "agent_id": agent_id, "surface": surface}
