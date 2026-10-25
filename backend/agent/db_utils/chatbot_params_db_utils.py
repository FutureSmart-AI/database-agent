import time
from datetime import datetime, timedelta
from agent.db_utils.common_db_utils import get_connection
from agent.db_utils.common_postresql_utils import execute_sql_query, db_rows_affected_log

from logger import logger
from sqlmodel import select
from models.sql_models import ChatbotDetails
from agent.services.sqlmodel_session import get_async_session
from otel_tracing import track_time

@track_time("DB: Get Chatbot Parameters")
async def get_chatbot_parameters(user_id, agent_id):
    """
    Get chatbot parameters by agent_id.
    Queries by agent_id OR chatbot_id for backward compatibility.

    Args:
        user_id: User ID (can be None for new RESTful endpoints)
        agent_id: Agent ID
    """
    start_time = time.time()
    try:
        from sqlalchemy import or_
        async for session in get_async_session():
            # Query by agent_id OR chatbot_id for backward compatibility
            query = select(ChatbotDetails).where(
                ChatbotDetails.deleted != True,
                or_(
                    ChatbotDetails.agent_id == agent_id,
                    ChatbotDetails.chatbot_id == agent_id
                )
            )
            # Add user_id filter only if provided
            if user_id:
                query = query.where(ChatbotDetails.user_id == user_id)

            res = await session.execute(query)
            bot = res.scalars().first()
            if bot:
                result = {
                    "user_id": bot.user_id,
                    "agent_id": bot.agent_id or bot.chatbot_id,  # Use agent_id, fallback to chatbot_id for backward compatibility
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

async def update_chatbot_parameters(user_id, agent_id, chatbot_name=None, system_prompt=None, greet_message=None, provider=None, model=None, temperature=None):
    """
    Update chatbot parameters by agent_id.
    Queries by agent_id OR chatbot_id for backward compatibility.

    Args:
        user_id: User ID (can be None for new RESTful endpoints)
        agent_id: Agent ID
        chatbot_name: Optional new chatbot name
        system_prompt: Optional new system prompt
        greet_message: Optional new greet message
        provider: Optional new LLM provider
        model: Optional new model
        temperature: Optional new temperature
    """
    start_time = time.time()
    try:
        from sqlalchemy import or_
        async for session in get_async_session():
            # Query by agent_id OR chatbot_id for backward compatibility
            query = select(ChatbotDetails).where(
                ChatbotDetails.deleted != True,
                or_(
                    ChatbotDetails.agent_id == agent_id,
                    ChatbotDetails.chatbot_id == agent_id
                )
            )
            # Add user_id filter only if provided
            if user_id:
                query = query.where(ChatbotDetails.user_id == user_id)

            res = await session.execute(query)
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
            logger.info(f"Chatbot parameters updated in {time.time() - start_time} seconds.")
            return {"message": "Chatbot parameters updated successfully", "status": True}
    except Exception as e:
        logger.error("Exception in update_chatbot_parameters: %s", str(e))
        return {"message": f"Error in update_chatbot_parameters: {str(e)}", "status": False}