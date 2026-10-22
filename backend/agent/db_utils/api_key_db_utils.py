import uuid
from datetime import datetime
from logger import logger
from models.sql_models import ApiKeys
from agent.services.sqlmodel_session import get_async_session
from sqlmodel import select, update, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List, Dict, Any, Tuple
from otel_tracing import track_time


def _agent_match(agent_id: str):
    """Match a key to an agent.

    Keys are written with both `agent_id` and `chatbot_id` set, but rows predating the
    RESTful `agent_id` column only carry `chatbot_id`, so both are checked.
    """
    return or_(ApiKeys.agent_id == agent_id, ApiKeys.chatbot_id == agent_id)


@track_time("DB: Validate API Key")
async def validate_api_key(api_key: str) -> Optional[dict]:
    """Validate if an API key exists and is active."""
    async for session in get_async_session():
        query = select(ApiKeys).where(ApiKeys.api_key == api_key, ApiKeys.is_active == True)
        result = await session.execute(query)
        row = result.scalar_one_or_none()
        if not row:
            logger.warning(f"Invalid or inactive API key attempted to be used")
            return None
        logger.info(f"API key validated for user {row.user_id}")
        return {
            "user_id": row.user_id,
            "chatbot_id": row.chatbot_id,
            "agent_id": row.agent_id or row.chatbot_id,
        }


@track_time("DB: Generate API Key")
async def generate_api_key(agent_id: str, user_id: str) -> Tuple[str, Optional[datetime], bool]:
    """Issue an API key for one agent.

    A user holds at most one active key per agent: if they already have one it is returned
    unchanged instead of minting a second, so repeated calls from the dashboard are safe.

    Returns `(api_key, created_at, already_existed)`.
    """
    try:
        async for session in get_async_session():
            statement = select(ApiKeys).where(
                and_(
                    ApiKeys.user_id == user_id,
                    _agent_match(agent_id),
                    ApiKeys.is_active == True,
                )
            )
            result = await session.execute(statement)
            existing_key = result.scalars().first()

            if existing_key:
                logger.info(f"User {user_id} already has an active API key for agent {agent_id}")
                return existing_key.api_key, existing_key.created_at, True

            api_key = str(uuid.uuid4())
            # chatbot_id mirrors agent_id here, as it does on every other agent-scoped table.
            new_api_key = ApiKeys(
                user_id=user_id,
                chatbot_id=agent_id,
                agent_id=agent_id,
                api_key=api_key,
            )
            session.add(new_api_key)
            await session.commit()
            await session.refresh(new_api_key)
            logger.info(
                f"Generated new API key for user {user_id} on agent {agent_id} "
                f"(agent-scoped)"
            )
            return api_key, new_api_key.created_at, False
    except Exception as e:
        logger.error(f"Database error occurred during generate_api_key: {str(e)}")
        raise


@track_time("DB: Get API Keys")
async def get_agent_api_keys(agent_id: str, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """List an agent's API keys, newest first.

    `user_id` narrows the result to one owner's keys; omit it (master-key callers) to see
    every key issued for the agent. Revoked keys are included so the caller can show history.
    """
    try:
        async for session in get_async_session():
            conditions = [_agent_match(agent_id)]
            if user_id is not None:
                conditions.append(ApiKeys.user_id == user_id)

            statement = (
                select(ApiKeys)
                .where(and_(*conditions))
                .order_by(ApiKeys.created_at.desc())
            )
            result = await session.execute(statement)
            api_keys = result.scalars().all()

            logger.info(f"Retrieved {len(api_keys)} API keys for agent {agent_id}, user {user_id}")
            return [
                {
                    "api_key": key.api_key,
                    "agent_id": key.agent_id or key.chatbot_id,
                    "user_id": key.user_id,
                    "is_active": key.is_active,
                    "created_at": key.created_at,
                    "revoked_at": key.revoked_at,
                }
                for key in api_keys
            ]
    except Exception as e:
        logger.error(f"Database error occurred during get_agent_api_keys: {str(e)}")
        raise


@track_time("DB: Revoke API Key")
async def revoke_api_key(api_key: str, agent_id: str, user_id: Optional[str] = None) -> bool:
    """Deactivate one key.

    Scoped to `agent_id` so a caller authorized on one agent cannot revoke another agent's
    key by guessing its value. `user_id`, when given, restricts revocation to one's own keys.
    Returns False when there is no matching active key.
    """
    try:
        async for session in get_async_session():
            conditions = [
                ApiKeys.api_key == api_key,
                _agent_match(agent_id),
                ApiKeys.is_active == True,
            ]
            if user_id is not None:
                conditions.append(ApiKeys.user_id == user_id)

            statement = select(ApiKeys).where(and_(*conditions))
            result = await session.execute(statement)
            api_key_record = result.scalar_one_or_none()

            if not api_key_record:
                logger.warning(
                    f"Attempted to revoke a non-existent or already revoked API key on agent {agent_id}"
                )
                return False

            api_key_record.is_active = False
            api_key_record.revoked_at = datetime.utcnow()
            await session.commit()
            logger.info(f"Revoked API key on agent {agent_id}")
            return True
    except Exception as e:
        logger.error(f"Database error occurred during revoke_api_key: {str(e)}")
        raise
