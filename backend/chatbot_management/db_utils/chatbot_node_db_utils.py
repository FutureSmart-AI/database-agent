from datetime import datetime
from typing import List, Optional, Dict, Any
from sqlmodel import select
from models.sql_models import ChatbotNodeConfig
from chatbot_management.services.sqlmodel_session import get_async_session
from logger import logger

async def get_node_configs_from_db(agent_id: str, node_name: Optional[str] = None) -> List[ChatbotNodeConfig]:
    """
    Fetch node configurations for a specific agent from the database.

    Soft-deleted rows (deleted_at set) are excluded — a node reset to default keeps its row
    for the audit trail but must not be treated as configured.
    """
    try:
        async for session in get_async_session():
            query = select(ChatbotNodeConfig).where(
                ChatbotNodeConfig.agent_id == agent_id,
                ChatbotNodeConfig.deleted_at.is_(None),
            )
            if node_name:
                query = query.where(ChatbotNodeConfig.node_name == node_name)
            
            result = await session.execute(query)
            return result.scalars().all()
    except Exception as e:
        logger.error(f"Error getting node configs from DB: {str(e)}")
        return []

async def upsert_node_configs_in_db(agent_id: str, configs: List[Any], user_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Update or insert node configurations in the database.

    user_id: acting dashboard user; stamped only when truthy so internal/API-key
    (master) calls don't clobber the last dashboard editor with NULL.
    """
    updated_nodes = []
    try:
        async for session in get_async_session():
            for config in configs:
                # Check if node config already exists. Deliberately NOT filtered on
                # deleted_at: a soft-deleted row must be found and revived, otherwise we
                # would insert a second row for the same (agent_id, node_name) and the
                # scalar_one_or_none() readers would raise MultipleResultsFound.
                existing_result = await session.execute(
                    select(ChatbotNodeConfig).where(
                        ChatbotNodeConfig.agent_id == agent_id,
                        ChatbotNodeConfig.node_name == config.node_name
                    )
                )
                existing_node = existing_result.scalars().first()

                if existing_node:
                    # Update existing
                    existing_node.provider = config.provider
                    existing_node.model = config.model
                    existing_node.temperature = config.temperature
                    existing_node.prompt = config.prompt
                    existing_node.updated_at = datetime.utcnow()
                    # Reconfiguring a reset node revives it — clear the delete audit so the
                    # row reads as live again.
                    existing_node.deleted_at = None
                    existing_node.deleted_by = None
                    # Ensure agent_id is synced
                    if not existing_node.agent_id:
                        existing_node.agent_id = agent_id
                    if user_id:
                        existing_node.updated_by = user_id  # acting dashboard user on this edit
                        if not existing_node.user_id:
                            # Row predates user_id being recorded — adopt the first known
                            # actor as the creator rather than leaving it NULL forever.
                            existing_node.user_id = user_id
                else:
                    # Insert new
                    new_node = ChatbotNodeConfig(
                        chatbot_id=agent_id,
                        agent_id=agent_id,
                        user_id=user_id,
                        node_name=config.node_name,
                        provider=config.provider,
                        model=config.model,
                        temperature=config.temperature,
                        prompt=config.prompt
                    )
                    session.add(new_node)

                updated_nodes.append({
                    "node_name": config.node_name,
                    "updated_at": datetime.utcnow().isoformat()
                })
            
            await session.commit()
            return updated_nodes
    except Exception as e:
        logger.error(f"Error upserting node configs in DB: {str(e)}")
        raise

async def delete_node_config_from_db(agent_id: str, node_name: str, deleted_by: Optional[str] = None) -> bool:
    """
    Soft-delete a specific node configuration (resetting the node to its default).

    The row is retained with deleted_at/deleted_by set so the reset is auditable — a hard
    delete would leave nothing to record who did it. Readers filter on deleted_at, and
    reconfiguring the node revives the same row, so behaviour matches the previous hard
    delete. Returns False when the node has no live config to reset.

    deleted_by: acting dashboard user; NULL for internal / API-key (master) callers.
    """
    try:
        async for session in get_async_session():
            node_result = await session.execute(
                select(ChatbotNodeConfig).where(
                    ChatbotNodeConfig.agent_id == agent_id,
                    ChatbotNodeConfig.node_name == node_name,
                    ChatbotNodeConfig.deleted_at.is_(None),
                )
            )
            node = node_result.scalar_one_or_none()

            if node:
                node.deleted_at = datetime.utcnow()
                if deleted_by:
                    node.deleted_by = deleted_by  # acting dashboard user on the reset
                await session.commit()
                return True
            return False
    except Exception as e:
        logger.error(f"Error deleting node config from DB: {str(e)}")
        raise
