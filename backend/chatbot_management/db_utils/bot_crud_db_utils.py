# import time
from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlmodel import select, func
from models.sql_models import ChatbotDetails, ChatbotInvitations, ChatLogs, ChatSessions
from chatbot_management.services.sqlmodel_session import get_async_session
from logger import logger
from datetime import datetime
from uuid import uuid4

async def insert_chatbot_details(chatbot_details: dict):
    try:
        async for session in get_async_session():
            # Ensure both agent_id and chatbot_id are set for consistency
            if 'chatbot_id' in chatbot_details and 'agent_id' not in chatbot_details:
                chatbot_details['agent_id'] = chatbot_details['chatbot_id']
            elif 'agent_id' in chatbot_details and 'chatbot_id' not in chatbot_details:
                chatbot_details['chatbot_id'] = chatbot_details['agent_id']

            chatbot = ChatbotDetails(**chatbot_details)
            session.add(chatbot)
            await session.commit()
            await session.refresh(chatbot)
            return chatbot
    except Exception as e:
        logger.error(f"Error inserting chatbot details: {e}")
        return None

async def get_chatbot_details(user_id: str):
    try:
        async for session in get_async_session():
            statement = select(ChatbotDetails).where(ChatbotDetails.user_id == user_id, ChatbotDetails.deleted == False)
            results = await session.execute(statement)
            chatbots = results.scalars().all()
            return chatbots
    except Exception as e:
        logger.error(f"Error getting chatbot details: {e}")
        return []

async def delete_chatbot_details(chatbot_id: str, deleted_by: str = None):
    """Soft-delete an agent.

    deleted_by: acting dashboard user (email); None for internal / master-key callers.
    """
    try:
        async for session in get_async_session():
            statement = select(ChatbotDetails).where(ChatbotDetails.chatbot_id == chatbot_id)
            results = await session.execute(statement)
            chatbot = results.scalars().one_or_none()
            if chatbot:
                chatbot.deleted = True
                chatbot.deleted_at = datetime.now()
                chatbot.deleted_by = deleted_by
                await session.commit()
                await session.refresh(chatbot)
                return chatbot
            return None
    except Exception as e:
        logger.error(f"Error deleting chatbot details: {e}")
        return None

async def get_invited_chatbots(user_email: str):
    try:
        async for session in get_async_session():
            statement = select(ChatbotInvitations).where(ChatbotInvitations.invited_user_email == user_email)
            results = await session.execute(statement)
            invitations = results.scalars().all()
            chatbot_ids = [inv.chatbot_id for inv in invitations]
            if not chatbot_ids:
                return []
            chatbot_statement = select(ChatbotDetails).where(ChatbotDetails.chatbot_id.in_(chatbot_ids), ChatbotDetails.deleted == False)
            chatbot_results = await session.execute(chatbot_statement)
            chatbots = chatbot_results.scalars().all()
            return chatbots
    except Exception as e:
        logger.error(f"Error getting invited chatbots: {e}")
        return []



# ============================================================================
# Agent (RESTful) DB Utils
# ============================================================================

async def get_agent_by_id(agent_id: str) -> Optional[ChatbotDetails]:
    """Retrieve a single agent by ID"""
    try:
        async for session in get_async_session():
            # RESTful endpoints use agent_id column
            statement = select(ChatbotDetails).where(
                ChatbotDetails.agent_id == agent_id,
                ChatbotDetails.deleted == False
            )
            results = await session.execute(statement)
            agent = results.scalars().one_or_none()
            return agent
    except Exception as e:
        logger.error(f"Error getting agent by ID: {e}")
        return None


async def get_agents_by_owner_id(owner_id: str) -> List[ChatbotDetails]:
    """Retrieve all agents owned by a specific user email (owner_id)"""
    try:
        async for session in get_async_session():
            # Filter by owner_id (email) directly
            statement = select(ChatbotDetails).where(
                ChatbotDetails.owner_id == owner_id,
                ChatbotDetails.deleted == False
            )
            results = await session.execute(statement)
            agents = list(results.scalars().all())
            return agents
    except Exception as e:
        logger.error(f"Error getting agents by owner ID: {e}")
        return []


async def get_all_agents() -> List[ChatbotDetails]:
    """Retrieve all non-deleted agents"""
    try:
        async for session in get_async_session():
            statement = select(ChatbotDetails).where(ChatbotDetails.deleted == False)
            results = await session.execute(statement)
            agents = list(results.scalars().all())
            return agents
    except Exception as e:
        logger.error(f"Error getting all agents: {e}")
        return []


async def update_agent_details(agent_id: str, update_data: dict, updated_by: Optional[str] = None) -> Optional[ChatbotDetails]:
    """Update agent in database using agent_id.

    updated_by: acting dashboard user (email); stamped only when truthy so internal /
    API-key (master) calls leave it NULL. updated_at is set on every edit.
    """
    try:
        async for session in get_async_session():
            statement = select(ChatbotDetails).where(
                ChatbotDetails.agent_id == agent_id,
                ChatbotDetails.deleted == False
            )
            results = await session.execute(statement)
            agent = results.scalars().one_or_none()

            if not agent:
                return None

            # Update only provided fields
            for key, value in update_data.items():
                if value is not None:
                    # Map agent_name to chatbot_name for consistency
                    if key == "agent_name":
                        setattr(agent, "chatbot_name", value)
                    elif key == "provider":
                        setattr(agent, "llm_provider", value)
                    else:
                        setattr(agent, key, value)

            agent.updated_at = datetime.utcnow()
            if updated_by:
                agent.updated_by = updated_by  # stamp the acting dashboard user

            await session.commit()
            await session.refresh(agent)
            return agent
    except Exception as e:
        logger.error(f"Error updating agent: {e}")
        return None


# ============================================================================
# Chat (RESTful) DB Utils
# ============================================================================

async def get_past_conversation(session_id: str) -> List[Dict[str, str]]:
    """Retrieve formatted past conversation for a session"""
    try:
        messages = []
        async for session in get_async_session():
            res = await session.execute(
                select(ChatLogs).where(ChatLogs.session_id == session_id).order_by(ChatLogs.created_at)
            )
            rows = res.scalars().all()
            for chat_log in rows:
                if chat_log.user_query:
                    messages.append({"role": "user", "content": chat_log.user_query})
                if chat_log.gpt_response:
                    messages.append({"role": "assistant", "content": chat_log.gpt_response})
        return messages
    except Exception as e:
        logger.error(f"Error getting past conversation: {e}")
        return []


async def get_owner_email_by_agent_id(agent_id: str) -> Optional[str]:
    """Retrieve owner email address by agent_id"""
    try:
        async for session in get_async_session():
            res = await session.execute(
                select(ChatbotDetails.owner_id).where(ChatbotDetails.agent_id == agent_id).limit(1)
            )
            row = res.first()
            if row is None:
                return None
            # Handle tuple vs object vs direct value based on query results
            return row if isinstance(row, str) else (row[0] if isinstance(row, tuple) else getattr(row, "owner_id", None))
    except Exception as e:
        logger.error(f"Error getting owner email by agent_id: {e}")
        return None

