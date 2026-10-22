"""
Business logic for agent statistics
"""
from typing import Optional
from fastapi import HTTPException
from chatbot_management.services.logger import logger


async def verify_agent_exists(agent_id: str) -> None:
    from models.sql_models import ChatbotDetails
    from chatbot_management.services.sqlmodel_session import get_async_session
    from sqlmodel import select

    async for session in get_async_session():
        result = await session.execute(
            select(ChatbotDetails).where(ChatbotDetails.agent_id == agent_id)
        )
        agent = result.scalar_one_or_none()
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")


async def get_agent_statistics_data(
    agent_id: str,
    start_time: Optional[str],
    end_time: Optional[str],
) -> dict:
    from chatbot_management.db_utils import bot_statistics_db_utils

    await verify_agent_exists(agent_id)

    result = await bot_statistics_db_utils.get_bot_statistics(
        chatbot_id=agent_id,
        start_datetime=start_time,
        end_datetime=end_time,
        user_id=None,
        use_agent_id=True
    )
    logger.info(f"Statistics fetched successfully for agent {agent_id}")
    return result
