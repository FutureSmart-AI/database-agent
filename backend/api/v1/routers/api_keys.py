"""
RESTful API endpoints for per-agent API keys

A key issued here authenticates only the agent it was issued for. Managing keys is
deliberately not something a key can do: these three routes reject `agent_api_key` auth and
require a session (or the master key), so a leaked key cannot mint or revoke others.
"""
from fastapi import HTTPException, Depends, APIRouter, Path
from starlette.requests import Request
from chatbot_management.utils.api_validation import get_api_key_or_session
from chatbot_management.services.logger import logger
import traceback

from api.v1.schemas.api_keys import (
    GenerateApiKeyRequest,
    ApiKeyResponse,
    ApiKeyListResponse,
)
from agent.utils.authorization import require_agent_permission
from api.v1.utils.api_keys_helper import issue_api_key, list_api_keys, revoke_agent_api_key

router = APIRouter(prefix="/v1")


def reject_agent_key_auth(auth: dict) -> None:
    """API keys cannot manage API keys — that would make any leaked key self-renewing."""
    if auth.get("auth_type") == "agent_api_key":
        raise HTTPException(
            status_code=403,
            detail="API keys cannot manage API keys. Use a signed-in session or the master API key.",
        )


@router.post("/agents/{agent_id}/api-keys", response_model=ApiKeyResponse, status_code=201)
async def generate_agent_api_key(
    agent_id: str = Path(..., description="Agent ID"),
    body: GenerateApiKeyRequest = GenerateApiKeyRequest(),
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("write")),
):
    """
    Generate an API key for an agent

    Returns the caller's existing active key if they already have one, so repeat calls are safe.
    """
    try:
        reject_agent_key_auth(auth)
        return await issue_api_key(agent_id, auth, requested_user_id=body.user_id if body else None)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating API key: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/agents/{agent_id}/api-keys", response_model=ApiKeyListResponse)
async def get_agent_api_keys(
    agent_id: str = Path(..., description="Agent ID"),
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("read")),
):
    """
    List an agent's API keys

    Session callers see their own keys; master-key callers see every key on the agent.
    """
    try:
        reject_agent_key_auth(auth)
        return await list_api_keys(agent_id, auth)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing API keys: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.delete("/agents/{agent_id}/api-keys/{api_key}")
async def revoke_api_key_for_agent(
    agent_id: str = Path(..., description="Agent ID"),
    api_key: str = Path(..., description="The API key to revoke"),
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("delete")),
):
    """
    Revoke an agent API key

    The key stops authenticating immediately. The row is kept, marked inactive with a
    `revoked_at` timestamp, so the listing still shows it.
    """
    try:
        reject_agent_key_auth(auth)
        return await revoke_agent_api_key(agent_id, api_key, auth)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error revoking API key: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
