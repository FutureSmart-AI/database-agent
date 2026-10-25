"""
RESTful API endpoints for Agent Configuration
Following REST best practices for managing agent configuration and parameters
Implements node-level LLM configurations for LangGraph nodes
"""
from fastapi import HTTPException, Depends, APIRouter, Query, Path, Request
from chatbot_management.utils.api_validation import get_api_key_or_session
from chatbot_management.services.logger import logger
import traceback
from typing import Optional

# Import schemas from centralized location
from api.v1.schemas.config import (
    NodeConfig,
    NodeConfigsRequest,
    AgentParamsRequest,
)
from agent.utils.authorization import require_agent_permission
from api.v1.utils.config_helper import (
    VALID_NODE_NAMES, NODE_CONFIG_MAP,
    get_agent_config_data, upsert_agent_node_configs,
    patch_agent_config_params, reset_node_to_default
)

router = APIRouter(prefix="/v1")


@router.get("/agents/{agent_id}/config")
async def get_agent_config(
    agent_id: str = Path(..., description="Agent ID"),
    fields: Optional[str] = Query(None, description="Comma-separated list of fields to return (e.g., nodes,agent_params)"),
    node_name: Optional[str] = Query(None, description="Filter specific node configuration"),
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("read")),
):
    """
    Get agent configuration including nodes and agent parameters

    """
    try:
        user_id = auth.get("user_id")
        logger.info(f"Getting config for agent {agent_id}, user_id={user_id}")
        return await get_agent_config_data(user_id, agent_id, fields, node_name)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting agent config: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/agents/{agent_id}/config/nodes")
async def upsert_node_configs(
    agent_id: str = Path(..., description="Agent ID"),
    body: NodeConfigsRequest = None,
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("write")),
):
    """
    Upsert (create or update) node configurations for an agent

    """
    try:
        current_user_id = auth.get("user_id")
        auth_type = auth.get("auth_type")
        logger.info(f"Upserting node configs for agent {agent_id}, user_id {current_user_id}, auth_type: {auth_type}")
        # Only stamp the acting user for dashboard (session) writes; internal/API-key calls leave it NULL.
        return await upsert_agent_node_configs(agent_id, body, user_id=current_user_id if auth_type == "session" else None)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error upserting node configs: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.patch("/agents/{agent_id}/config/params")
async def patch_agent_params(
    agent_id: str = Path(..., description="Agent ID"),
    body: AgentParamsRequest = None,
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("write")),
):
    """
    Partially update agent parameters

    """
    try:
        current_user_id = auth.get("user_id")
        auth_type = auth.get("auth_type")
        logger.info(f"Updating params for agent {agent_id}, user_id {current_user_id}, auth_type: {auth_type}")
        return await patch_agent_config_params(agent_id, body, auth_type, current_user_id)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating agent params: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.delete("/agents/{agent_id}/config/nodes/{node_name}")
async def reset_to_default(
    agent_id: str = Path(..., description="Agent ID"),
    node_name: str = Path(..., description="Node name (must be one of the valid LangGraph nodes)"),
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("write")),
):
    """
    Delete a node configuration

    """
    try:
        user_id = auth.get("user_id")
        logger.info(f"Resetting to default node config {node_name} for agent {agent_id}, user_id={user_id}")
        return await reset_node_to_default(agent_id, node_name, user_id=user_id)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting node config: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
