from agent.utils.model_profiles import ModelConfigurationError, merge_binding, operation_config
"""
Utility to load agent-specific LLM configuration from database.
This allows per-agent and per-node model/provider/temperature overrides.
"""
from typing import Optional, Dict, Any
from logger import logger
from models.sql_models import ChatbotNodeConfig, ChatbotDetails
from agent.services.sqlmodel_session import get_async_session
from sqlmodel import select


async def get_agent_node_config(agent_id: Optional[str], node_name: str) -> Optional[Dict[str, Any]]:
    """
    Load node-specific LLM configuration from database.
    Falls back to agent-level config if no node-specific config exists.

    Args:
        agent_id: The agent ID to load configuration for
        node_name: The node name (e.g., 'router', 'sql_gen', 'final_answer_node')

    Returns:
        Dictionary with 'provider', 'model', and 'temperature' if configured,
        None otherwise
    """
    if not agent_id:
        return None

    try:
        async for session in get_async_session():
            # First, try to get node-specific configuration
            node_result = await session.execute(
                select(ChatbotNodeConfig).where(
                    ChatbotNodeConfig.agent_id == agent_id,
                    ChatbotNodeConfig.node_name == node_name,
                    ChatbotNodeConfig.deleted_at.is_(None),  # a node reset to default keeps its row
                )
            )
            node_config = node_result.scalar_one_or_none()

            if node_config:
                if (node_config.provider is None and node_config.model is None
                        and node_config.temperature is None
                        and isinstance(node_config.prompt, str) and node_config.prompt.strip()):
                    # A business template supplies instructions while inheriting
                    # the versioned operation profile, including rich file options.
                    return None
                if not node_config.provider or not node_config.model:
                    raise ModelConfigurationError(f"Incomplete stored model binding for {node_name}")
                config = {
                    "provider": node_config.provider,
                    "model": node_config.model,
                    "temperature": node_config.temperature
                }
                logger.info(f"📋 [NODE_CONFIG] Loaded from DB | agent_id: {agent_id} | node: {node_name} | provider: {config['provider']} | model: {config['model']} | temperature: {config['temperature']}")
                return operation_config(node_name, config)

            # # Fall back to agent-level configuration
            # agent_result = await session.execute(
            #     select(ChatbotDetails).where(
            #         ChatbotDetails.agent_id == agent_id,
            #         ChatbotDetails.deleted != True
            #     )
            # )
            # agent = agent_result.scalar_one_or_none()

            # if agent and agent.llm_provider and agent.model:
            #     config = {
            #         "provider": agent.llm_provider,
            #         "model": agent.model,
            #         "temperature": agent.temperature if agent.temperature is not None else 0.0
            #     }
            #     logger.info(f"📋 [AGENT_CONFIG] Loaded from DB (fallback) | agent_id: {agent_id} | node: {node_name} | provider: {config['provider']} | model: {config['model']} | temperature: {config['temperature']}")
            #     return config
            # else:
            #     logger.info(f"📋 [CONFIG] No config in DB for agent_id: {agent_id}, node: {node_name}, will use model_config.json")
            #     return None

    except ModelConfigurationError:
        raise
    except Exception as error:
        raise ModelConfigurationError(f"Cannot load stored model configuration for {node_name}") from error


async def get_agent_llm_config(agent_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    Load agent-level LLM configuration from database.
    This is kept for backward compatibility.

    Args:
        agent_id: The agent ID to load configuration for

    Returns:
        Dictionary with 'provider', 'model', and 'temperature' if agent found and configured,
        None otherwise
    """
    if not agent_id:
        return None

    try:
        async for session in get_async_session():
            result = await session.execute(
                select(ChatbotDetails).where(
                    ChatbotDetails.agent_id == agent_id,
                    ChatbotDetails.deleted != True
                )
            )
            agent = result.scalar_one_or_none()

            if agent and agent.llm_provider and agent.model:
                config = {
                    "provider": agent.llm_provider,
                    "model": agent.model,
                    "temperature": agent.temperature if agent.temperature is not None else 0.0
                }
                logger.info(f"📋 [AGENT_CONFIG] Loaded from DB | agent_id: {agent_id} | provider: {config['provider']} | model: {config['model']} | temperature: {config['temperature']}")
                return config
            else:
                logger.info(f"📋 [AGENT_CONFIG] No LLM config in DB for agent_id: {agent_id}, will use model_config.json")
                return None

    except Exception as e:
        logger.warning(f"📋 [AGENT_CONFIG] Failed to load agent config from DB for agent_id: {agent_id}, error: {e}")
        return None


def merge_agent_config_with_defaults(
    agent_config: Optional[Dict[str, Any]],
    default_config: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Merge agent-specific configuration with default configuration.
    Agent config takes precedence over defaults.
    
    Args:
        agent_config: Agent-specific config from database (can be None)
        default_config: Default config from model_config.json
        
    Returns:
        Merged configuration dictionary
    """
    return merge_binding(default_config, agent_config)
