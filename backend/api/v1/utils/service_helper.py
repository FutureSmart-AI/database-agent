"""
Business logic for NL2SQL service validation and listing
"""
from typing import Optional, List
from chatbot_management.services.logger import logger


async def validate_nl2sql_service(owner_id: str, service_id: str) -> bool:
    from models.sql_models import ChatbotDetails
    from chatbot_management.services.sqlmodel_session import get_async_session
    from sqlmodel import select

    async for session in get_async_session():
        statement = select(ChatbotDetails).where(
            ChatbotDetails.agent_id == service_id,
            ChatbotDetails.owner_id == owner_id,
            ChatbotDetails.deleted == False
        )
        results = await session.execute(statement)
        service = results.scalars().one_or_none()
        if service:
            logger.info(f"NL2SQL service validation successful - owner_id: {owner_id}, service_id: {service_id}")
            return True
        logger.info(f"NL2SQL service validation failed - owner_id: {owner_id}, service_id: {service_id}")
        return False


async def list_nl2sql_services(owner_id: Optional[str]) -> List[str]:
    from models.sql_models import ChatbotDetails
    from chatbot_management.services.sqlmodel_session import get_async_session
    from sqlmodel import select

    async for session in get_async_session():
        if owner_id:
            statement = select(ChatbotDetails).where(
                ChatbotDetails.owner_id == owner_id,
                ChatbotDetails.deleted == False
            )
        else:
            statement = select(ChatbotDetails).where(ChatbotDetails.deleted == False)

        results = await session.execute(statement)
        services = results.scalars().all()
        service_ids = [s.agent_id for s in services if s.agent_id]
        logger.info(f"Found {len(service_ids)} NL2SQL services")
        return service_ids
