import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from chatbot_management.db_utils.common_db_utils import get_connection
from chatbot_management.services.logger import logger
from sqlmodel import select
from models.sql_models import ChatbotDetails
from chatbot_management.services.sqlmodel_session import get_async_session

# Request-payload field name -> ChatbotDetails attribute, where the two differ.
_COLUMN_ALIASES = {
    "agent_name": "chatbot_name",
    "provider": "llm_provider",
}

async def get_chatbot_parameters(user_id, chatbot_id):
    start_time = time.time()
    try:
        async for session in get_async_session():
            res = await session.execute(
                select(ChatbotDetails).where(
                    ChatbotDetails.user_id == user_id,
                    ChatbotDetails.chatbot_id == chatbot_id,
                    ChatbotDetails.deleted != True
                )
            )
            bot = res.scalars().first()
            if bot:
                result = {
                    "user_id": bot.user_id,
                    "chatbot_id": bot.chatbot_id,
                    "chatbot_name": bot.chatbot_name,
                    "provider": bot.llm_provider,
                    "model": bot.model,
                    "system_prompt": bot.system_prompt,
                    "greet_message": bot.greet_message,
                    "temperature": bot.temperature,
                }
                logger.info(f"Chatbot parameters - db utils completion in {time.time() - start_time} seconds.")
                return {"status": True, "params": result}
            else:
                return {"status": False, "message": "No chatbot parameters found"}
    except Exception as e:
        logger.error("Exception in get_chatbot_parameters: %s", str(e))
        return {"message": "Error in get_chatbot_parameters", "status": False}

async def update_chatbot_parameters(user_id, chatbot_id, chatbot_name=None, system_prompt=None, greet_message=None, provider=None, model=None, temperature=None):
    start_time = time.time()
    try:
        async for session in get_async_session():
            res = await session.execute(
                select(ChatbotDetails).where(
                    ChatbotDetails.user_id == user_id,
                    ChatbotDetails.chatbot_id == chatbot_id,
                    ChatbotDetails.deleted != True
                )
            )
            bot = res.scalars().first()
            if not bot:
                return {"message": "Chatbot not found or deleted", "status": False}
            if chatbot_name is not None:
                bot.chatbot_name = chatbot_name
            if system_prompt is not None:
                bot.system_prompt = system_prompt
            if greet_message is not None:
                bot.greet_message = greet_message
            if provider is not None:
                bot.llm_provider = provider
            if model is not None:
                bot.model = model
            if temperature is not None:
                bot.temperature = temperature
            await session.commit()
            return {"message": "Chatbot parameters updated successfully", "status": True}
    except Exception as e:
        logger.error("Exception in update_chatbot_parameters: %s", str(e))
        return {"message": f"Error in update_chatbot_parameters: {str(e)}", "status": False}

async def get_chatbot_details_by_agent_id(agent_id: str) -> Optional[ChatbotDetails]:
    try:
        async for session in get_async_session():
            result = await session.execute(
                select(ChatbotDetails).where(
                    ChatbotDetails.agent_id == agent_id,
                    ChatbotDetails.deleted != True
                )
            )
            return result.scalar_one_or_none()
    except Exception as e:
        logger.error(f"Error getting chatbot details by agent_id: {str(e)}")
        return None

async def update_chatbot_details_by_agent_id(agent_id: str, update_data: Dict[str, Any], owner_id: Optional[str] = None) -> Optional[ChatbotDetails]:
    try:
        async for session in get_async_session():
            query = select(ChatbotDetails).where(
                ChatbotDetails.agent_id == agent_id,
                ChatbotDetails.deleted != True
            )
            if owner_id:
                query = query.where(ChatbotDetails.owner_id == owner_id)
            result = await session.execute(query)
            agent = result.scalar_one_or_none()
            if not agent:
                return None
            for key, value in update_data.items():
                if value is None:
                    continue
                # Resolve the request-side name to the model attribute BEFORE the hasattr
                # guard: neither alias exists on the model (the columns are chatbot_name and
                # llm_provider), so checking the raw key first silently drops both.
                attr = _COLUMN_ALIASES.get(key, key)
                if hasattr(agent, attr):
                    setattr(agent, attr, value)
            await session.commit()
            await session.refresh(agent)
            return agent
    except Exception as e:
        logger.error(f"Error updating chatbot details by agent_id: {str(e)}")
        raise