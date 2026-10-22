## For the X-API Key Authorization of all API Endpoints
from fastapi.security import APIKeyHeader, APIKeyQuery
from fastapi import Depends, HTTPException, Header, status,Request
from starlette.status import HTTP_401_UNAUTHORIZED
from fastapi import Security, HTTPException
import os
import logging

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Ensure the correct dotenv file is loaded for the current environment.
# Example: MODE=DEV -> load ".env.dev"
# MODE = os.getenv("MODE", "").strip().upper()
# dotenv_path = None
# if MODE:
#     candidate = f".env.{MODE.lower()}"
#     if os.path.exists(candidate):
#         dotenv_path = candidate
#     logger.info("Loading dotenv for auth | MODE=%s dotenv_path=%s", MODE, dotenv_path)
# else:
#     logger.info("Loading dotenv for auth | MODE not set, using default .env")

# load_dotenv(dotenv_path=dotenv_path)
# Rely on main.py or central config loader
logger.info("Auth validation module initialized | Current MODE: %s", os.getenv("MODE"))

from chatbot_management.utils.auth import get_auth_details
from typing import Optional

API_KEY_NAME = os.getenv("FASTAPI_SECRET_KEY")

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

async def get_api_key(
    api_key: str = Security(api_key_header)
):
    # Defensive: handle multiple headers
    if api_key:
        for key in api_key.split(","):
            if key.strip() == API_KEY_NAME:
                return True
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid API Key"
    )

async def get_api_key_or_session(
    request: Request,
    api_key: Optional[str] = Security(api_key_header),
):
    """
    Combined dependency that checks for either a valid session or a master API key.
    Prioritizes session authentication for browser users.
    """
    # 1. Check for session (Cognito)
    session_data = await get_auth_details(request, include_all_claims=True)
    if session_data:
        return {
            "auth_type": "session",
            "session_data": session_data,
            "user_id": session_data.get("email") or session_data.get("user_id")
        }

    # 2. Fallback to master API key
    logger.info(
        "Auth fallback to master key | path=%s method=%s has_x_api_key=%s expected_master_key_set=%s",
        getattr(request.url, "path", None),
        getattr(request, "method", None),
        bool(api_key),
        bool(API_KEY_NAME),
    )

    if api_key:
        keys = [k.strip() for k in api_key.split(",") if k.strip()]
        match = any((k == API_KEY_NAME) for k in keys)
        logger.info(
            "Auth master key compare | has_x_api_key=%s match=%s keys_count=%s",
            bool(api_key),
            match,
            len(keys),
        )

        if match:
            # Return a redacted-style placeholder (we don't need to propagate the raw key)
            return {
                "auth_type": "master_api_key",
                "api_key": "***",
                "user_id": None,  # Master key doesn't imply a specific user
            }

        # 3. Fallback to a per-agent API key issued by POST /v1/agents/{agent_id}/api-keys.
        # Unlike the master key these are scoped: a key only authenticates the agent it was
        # issued for, so it is accepted solely on routes that resolve to that same agent.
        # Imported here rather than at module scope because agent.utils.authorization
        # imports this module.
        from agent.db_utils.api_key_db_utils import validate_api_key
        from agent.utils.authorization import resolve_agent_id_from_request

        requested_agent_id = resolve_agent_id_from_request(request)

        for key in keys:
            try:
                record = await validate_api_key(key)
            except Exception as exc:
                # Distinguish "the key is bad" (falls through to 401) from "we could not check"
                logger.error("Agent API key lookup failed | %s", exc)
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Unable to verify API key",
                )

            if not record:
                continue

            key_agent_id = record.get("agent_id")
            if not key_agent_id:
                logger.warning("Agent API key has no agent scope | rejecting")
                continue

            if not requested_agent_id:
                logger.warning(
                    "Agent API key used on a route with no agent scope | path=%s",
                    getattr(request.url, "path", None),
                )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="This API key is agent-scoped and cannot be used on this endpoint",
                )

            if key_agent_id != requested_agent_id:
                logger.warning(
                    "Agent API key scope mismatch | key_agent_id=%s requested_agent_id=%s",
                    key_agent_id,
                    requested_agent_id,
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="This API key is not valid for this agent",
                )

            logger.info("Authenticated with agent API key | agent_id=%s", key_agent_id)
            return {
                "auth_type": "agent_api_key",
                "api_key": "***",
                "agent_id": key_agent_id,
                "user_id": record.get("user_id"),
            }

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated: valid session or API key required"
    )