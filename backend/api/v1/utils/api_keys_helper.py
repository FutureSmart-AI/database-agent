"""
Business logic for per-agent API keys.

Keys issued here are scoped to a single agent: `get_api_key_or_session` accepts one as
`X-API-Key`, and `require_agent_permission` then only lets it through on that agent's routes.
"""
from fastapi import HTTPException
from chatbot_management.services.logger import logger


async def verify_agent_exists(agent_id: str) -> None:
    from models.sql_models import ChatbotDetails
    from chatbot_management.services.sqlmodel_session import get_async_session
    from sqlmodel import select, or_

    async for session in get_async_session():
        result = await session.execute(
            select(ChatbotDetails).where(
                or_(ChatbotDetails.agent_id == agent_id, ChatbotDetails.chatbot_id == agent_id)
            )
        )
        agent = result.scalars().first()
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")


def resolve_key_owner(auth: dict, requested_user_id: str = None) -> str:
    """Decide whose key this is.

    Session callers own the keys they create — a client-supplied `user_id` is ignored so a
    key cannot be issued in someone else's name. Master-key callers have no identity of
    their own, so they must name the owner in the body.
    """
    if auth.get("auth_type") == "master_api_key":
        if not requested_user_id:
            raise HTTPException(
                status_code=400,
                detail="user_id is required in the request body when calling with the master API key",
            )
        return requested_user_id

    user_id = auth.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Could not determine the user from the session")
    return user_id


async def issue_api_key(agent_id: str, auth: dict, requested_user_id: str = None) -> dict:
    from agent.db_utils.api_key_db_utils import generate_api_key

    # Owner first: a master-key call with no user_id is a bad request, and saying so costs
    # nothing, while the agent lookup is a database round-trip.
    user_id = resolve_key_owner(auth, requested_user_id)
    await verify_agent_exists(agent_id)

    api_key, created_at, already_existed = await generate_api_key(agent_id=agent_id, user_id=user_id)

    logger.info(
        f"API key issued for agent {agent_id}, user {user_id} (existing={already_existed})"
    )

    return {
        "api_key": api_key,
        "agent_id": agent_id,
        "user_id": user_id,
        "created_at": created_at.isoformat() if created_at else None,
        "message": (
            "You already have an active API key for this agent. Use it, or revoke it before generating a new one."
            if already_existed
            else "API key generated successfully. Store it now — it is shown in full on every read, but treat it as a secret."
        ),
    }


async def list_api_keys(agent_id: str, auth: dict) -> dict:
    """List the caller's keys for an agent; master-key callers see every key on the agent."""
    from agent.db_utils.api_key_db_utils import get_agent_api_keys

    await verify_agent_exists(agent_id)

    user_id = None if auth.get("auth_type") == "master_api_key" else auth.get("user_id")
    keys = await get_agent_api_keys(agent_id=agent_id, user_id=user_id)

    return {
        "api_keys": [
            {
                "api_key": key["api_key"],
                "agent_id": key["agent_id"],
                "user_id": key["user_id"],
                "is_active": key["is_active"],
                "created_at": key["created_at"].isoformat() if key["created_at"] else None,
                "revoked_at": key["revoked_at"].isoformat() if key["revoked_at"] else None,
            }
            for key in keys
        ]
    }


async def revoke_agent_api_key(agent_id: str, api_key: str, auth: dict) -> dict:
    from agent.db_utils.api_key_db_utils import revoke_api_key

    await verify_agent_exists(agent_id)

    user_id = None if auth.get("auth_type") == "master_api_key" else auth.get("user_id")
    revoked = await revoke_api_key(api_key=api_key, agent_id=agent_id, user_id=user_id)

    if not revoked:
        raise HTTPException(
            status_code=404,
            detail="API key not found on this agent, already revoked, or not owned by you",
        )

    logger.info(f"API key revoked on agent {agent_id} by {user_id or 'master key'}")
    return {"message": "API key revoked"}
