"""Agent-scoped access control for the NL2SQL API.

⚠ ROLE-BASED ACCESS CONTROL IS CURRENTLY DISABLED FOR SESSION (BROWSER) CALLERS.

Until now every agent-scoped route asked the chat service's `/auth/check-access` who the caller
was on this agent. That made an agent created through `POST /v1/agents` unusable: the chat service
does not know an agent NL2SQL created, so it answered 404 "No agent found for service_id …" and
the very next call — attaching a database — was refused. NL2SQL is being made to stand on its own,
so the dependency was dropped rather than worked around.

What that means now: **a valid login is the only requirement.** Any authenticated user reaches any
agent, including its database host/user/port. There is no owner check and no viewer/editor
distinction. This is a deliberate, temporary trade — do not read `require_agent_permission` as
enforcing anything for session callers.

Unaffected: the master key (still a full bypass) and per-agent API keys (still scoped to their own
agent by `get_api_key_or_session`, plus `enforce_agent_key_restrictions`).

To restore RBAC: call `check_access_centralized` from the session branch of
`require_agent_permission` again and re-apply `enforce_role_path_rules`. Both are kept here,
currently unused, for exactly that.
"""
from __future__ import annotations

import os
from typing import Optional, Callable, Dict, Any

from fastapi import HTTPException, Request, Depends
import httpx

from chatbot_management.utils.api_validation import get_api_key_or_session
from logger import logger

CHAT_AUTH_BASE = os.getenv("CHAT_AUTH_BASE", "https://agent.futuresmart.ai/api/chat/v1/auth")
CHAT_AUTH_API_KEY = os.getenv("CHAT_AUTH_API_KEY", "")

# Keep compatibility with existing router permission names while enforcing
# centralized auth permissions from the implementation guide.
PERMISSION_MAP = {
    "use_agent": "use",
    "edit_agent": "write",
    "edit_examples": "write",
    "delete_agent": "delete",
    "invite_users": "invite",
    "read": "read",
    "use": "use",
    "write": "write",
    "delete": "delete",
    "invite": "invite",
}


def resolve_agent_id_from_request(request: Request) -> Optional[str]:
    """Best-effort agent_id resolver for agent-scoped routes."""
    if not request:
        return None
    # Path params first (RESTful routes)
    agent_id = (request.path_params or {}).get("agent_id")
    if agent_id:
        return agent_id
    # Legacy/alternate names
    chatbot_id = (request.path_params or {}).get("chatbot_id")
    if chatbot_id:
        return chatbot_id
    # Query params fallback
    try:
        q = request.query_params
        return q.get("agent_id") or q.get("chatbot_id")
    except Exception:
        return None


def map_permission(permission: str) -> str:
    mapped = PERMISSION_MAP.get(permission)
    if not mapped:
        raise HTTPException(status_code=400, detail=f"Unknown permission '{permission}'")
    return mapped


async def check_access_centralized(user_email: str, permission: str, agent_id: str) -> Dict[str, Any]:
    """Ask the chat service for the caller's role on this agent.

    UNUSED while RBAC is disabled — kept so restoring it is one call. This is the call that made
    newly created agents unusable: the chat service 404s on an agent it has never been told about.
    """
    if not CHAT_AUTH_API_KEY:
        logger.error("CHAT_AUTH_API_KEY is not configured")
        raise HTTPException(status_code=500, detail="Authorization not configured")

    headers = {"x-api-key": CHAT_AUTH_API_KEY, "accept": "application/json"}
    params = {"user_email": user_email, "permission": permission, "service_id": agent_id}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{CHAT_AUTH_BASE}/check-access",
                params=params,
                headers=headers,
            )
    except Exception as exc:
        logger.error(f"Auth service call failed: {exc}")
        raise HTTPException(status_code=503, detail="Auth service unavailable")

    if response.status_code == 200:
        data = response.json()
        if not data.get("has_permission"):
            raise HTTPException(
                status_code=403,
                detail=f"Permission '{permission}' denied for user '{user_email}'",
            )
        return data

    if response.status_code in (403, 404):
        detail = response.json().get("detail", "Access denied")
        raise HTTPException(status_code=response.status_code, detail=detail)

    raise HTTPException(status_code=503, detail="Auth service unavailable")


def enforce_agent_key_restrictions(request: Request, agent_id: str) -> None:
    """Limit what a per-agent API key can do on its own agent.

    A key is meant for programmatic use of an agent, not for administering it. It is blocked
    from the operations that would let a leaked key entrench itself, give itself away, remove
    the agent, or read the source database credentials — the last matching the rule already
    applied to the `editor` role.
    """
    path = (request.url.path or "").rstrip("/")
    method = (request.method or "").upper()

    denied_reason = None
    if "/api-keys" in path:
        denied_reason = "API keys cannot manage API keys"
    elif "/invitations" in path:
        denied_reason = "API keys cannot manage collaborators"
    elif path.endswith("/database-connection"):
        denied_reason = "API keys cannot view or update database connection details"
    elif method == "DELETE" and path.endswith(f"/agents/{agent_id}"):
        denied_reason = "API keys cannot delete the agent"

    if denied_reason:
        logger.warning(
            f"Access denied for agent API key: agent_id={agent_id} {method} {path} — {denied_reason}"
        )
        raise HTTPException(status_code=403, detail=denied_reason)


def enforce_role_path_rules(role: str, path: str, user_email: str, agent_id: str) -> None:
    """Per-role route limits. UNUSED while RBAC is disabled — kept so restoring it is one call.

    - viewer: chat, messages and feedback only
    - editor: everything except the database connection details
    """
    if role == "viewer":
        is_chat_endpoint = (
            path.endswith("/chat")
            or "/chat/" in path
            or "/messages" in path
            or path.endswith("/feedback")
        )
        if not is_chat_endpoint:
            logger.warning(f"Access denied for viewer role: user={user_email}, path={path}, agent_id={agent_id}")
            raise HTTPException(
                status_code=403,
                detail="Viewer role is only allowed to use the chat endpoint",
            )

    elif role == "editor":
        if path.endswith("/database-connection"):
            logger.warning(f"Access denied for editor role: user={user_email}, path={path}, agent_id={agent_id}")
            raise HTTPException(
                status_code=403,
                detail="Editor role is not allowed to view or update database connection details",
            )


def require_agent_permission(permission: str) -> Callable[..., Any]:
    """
    Authentication dependency. **Does not authorize session callers** — see the module docstring.

    - master key: full bypass, as before
    - per-agent API key: still scoped to its own agent, plus the key restrictions
    - session: any valid login is accepted for any agent (RBAC disabled)

    Kept as a dependency, with its signature and return shape unchanged, so that every router keeps
    receiving the same `user` dict and RBAC can be switched back on in this one place.
    """

    async def dependency(
        request: Request,
        auth: dict = Depends(get_api_key_or_session),
    ):
        agent_id = resolve_agent_id_from_request(request)
        if not agent_id:
            raise HTTPException(status_code=400, detail="agent_id is required")

        # Master key bypass
        if auth.get("auth_type") == "master_api_key":
            logger.info(
                f"[audit] auth=master_api_key user_id=master agent_id={agent_id} "
                f"db_id={(request.path_params or {}).get('db_id')} {request.method} {request.url.path}"
            )
            return {"is_master": True, "role": "owner", "agent_id": agent_id}

        # Per-agent API key: already proven to belong to this agent by get_api_key_or_session,
        # so no call to the central auth service is possible or needed — the key is the grant.
        if auth.get("auth_type") == "agent_api_key":
            key_agent_id = auth.get("agent_id")
            if key_agent_id != agent_id:
                logger.warning(
                    f"Agent API key scope mismatch at authorization | key_agent_id={key_agent_id} "
                    f"agent_id={agent_id}"
                )
                raise HTTPException(status_code=403, detail="This API key is not valid for this agent")

            mapped_permission = map_permission(permission)
            enforce_agent_key_restrictions(request, agent_id)

            logger.info(
                f"[audit] auth=agent_api_key user_id={auth.get('user_id')} agent_id={agent_id} "
                f"permission={mapped_permission} "
                f"db_id={(request.path_params or {}).get('db_id')} {request.method} {request.url.path}"
            )
            return {
                "is_master": False,
                "role": "api_key",
                "agent_id": agent_id,
                "user_id": auth.get("user_id"),
                "permission": mapped_permission,
                "auth_type": "agent_api_key",
            }

        session_data = auth.get("session_data") or {}
        user_email = session_data.get("email")
        user_id = session_data.get("user_id")

        if not user_email:
            raise HTTPException(status_code=401, detail="Not authenticated")

        mapped_permission = map_permission(permission)
        path = request.url.path

        # AUTHORIZATION IS DISABLED FOR SESSION CALLERS — see the module docstring.
        # A valid login is all that is required; the agent is not checked against the caller.
        # Restoring RBAC means calling check_access_centralized(...) here again and reinstating
        # the viewer/editor path rules removed alongside it (both kept below for that purpose).
        role = "owner"

        logger.info(
            f"[audit] user_id={user_id} email={user_email} role={role} rbac=disabled "
            f"permission={mapped_permission} agent_id={agent_id} "
            f"db_id={(request.path_params or {}).get('db_id')} {request.method} {path}"
        )

        return {
            "is_master": False,
            "role": role,
            "agent_id": agent_id,
            "email": user_email,
            "user_id": user_id,
            "permission": mapped_permission,
            "session_data": session_data,
        }

    return dependency


