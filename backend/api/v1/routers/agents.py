"""
RESTful API endpoints for NL2SQL Agents
Following REST best practices with proper HTTP methods and resource naming
"""
from fastapi import HTTPException, Depends, APIRouter, Query, Path, Request
from datetime import datetime
from chatbot_management.utils.api_validation import get_api_key_or_session
from chatbot_management.services.logger import logger
import traceback
from typing import List, Dict, Any, Optional

# Import schemas from centralized location
from api.v1.schemas.agents import (
    CreateAgentRequest,
    UpdateAgentRequest,
    PatchAgentRequest,
    AgentResponse,
    AgentListResponse,
    AgentParametersResponse,
    UpdateAgentParametersRequest,
)
from agent.utils.authorization import require_agent_permission
from api.v1.utils.agents_helper import (
    get_agent_by_id, get_owner_id_from_agent, update_agent_in_db,
    get_agents_list, paginate_agents, create_new_agent, format_agent_data,
    format_agent_response, delete_agent_from_db
)

router = APIRouter(prefix="/v1")


# ============================================================================
# RESTful Agent Endpoints
# ============================================================================

@router.get("/agent-templates")
async def get_agent_templates(auth: dict = Depends(get_api_key_or_session)):
    """Use-case templates that can be passed as `template_id` when creating an agent.

    Static and owner-independent, so the dashboard can render a picker without
    knowing anything about the caller.
    """
    from api.v1.utils.agent_templates import list_templates
    return {"templates": list_templates()}


@router.post("/agents", status_code=201)
async def create_agent(
    agent_data: CreateAgentRequest,
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session)
):
    """
    Create a new NL2SQL agent

    Gets owner_id (email) from Google Auth session.
    When using master X-API-Key (no session), uses owner_id from request body.
    """
    try:
        # Get owner_id (email) from auth dependency
        # - Session auth: use session email (trusted) and ignore any client-supplied owner_id
        # - Master API key: allow owner_id in request body (admin-style call)
        owner_email = auth.get("user_id")  # Email from session or None for master key
        auth_type = auth.get("auth_type")

        if auth_type == "session":
            logger.info(f"Got owner email from auth session: {owner_email}")
        elif auth_type == "master_api_key" and not owner_email:
            owner_email = agent_data.owner_id

        if not owner_email:
            raise HTTPException(
                status_code=400,
                detail=(
                    "owner_id (email) is required. Provide via Google Auth session, "
                    "or when using master X-API-Key provide owner_id in the request body."
                ),
            )

        if isinstance(owner_email, str) and "@" not in owner_email:
            raise HTTPException(status_code=400, detail="owner_id must be a valid email address")

        logger.info(f"Creating new agent - owner_email: {owner_email}, agent_name: {agent_data.agent_name}")

        agent_id = await create_new_agent(owner_email, agent_data)
        if agent_id:
            return {"agent_id": agent_id, "owner_id": owner_email, "message": "agent created successfully"}
        else:
            raise HTTPException(status_code=500, detail="Failed to create agent")

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Exception in create_agent: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error creating agent: {str(e)}")


@router.get("/agents")
async def list_agents(
    owner_id: Optional[str] = Query(None, description="Filter by owner email (optional)"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    auth: dict = Depends(get_api_key_or_session)
):
    """
    List all agents

    Returns all agents in the system.
    If owner_id (email) is provided, filters to show only agents owned by that email.
    """
    try:
        # If session auth, enforce owner_id = session email
        auth_type = auth.get("auth_type")
        if auth_type == "session":
            session_email = auth.get("user_id")
            if owner_id and owner_id.lower() != session_email.lower():
                raise HTTPException(status_code=403, detail="You can only list your own agents")
            owner_id = session_email

        logger.info(f"Listing agents, filter by owner_id (email): {owner_id}, auth_type: {auth_type}")

        agents_data = await get_agents_list(owner_id)
        pagination_result = paginate_agents(agents_data, page, limit)
        return {**pagination_result, "meta": {"timestamp": datetime.now().isoformat()}}

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Exception in list_agents: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error listing agents: {str(e)}")


@router.get("/agents/{agent_id}")
async def get_agent(
    agent_id: str = Path(..., description="Agent ID"),
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("use")),
):
    """
    Get a specific agent by ID

    The response includes the owner_id (email) of the agent.
    """
    try:
        user_id = auth.get("user_id")
        logger.info(f"Getting agent details for agent_id: {agent_id}, user_id={user_id}")
        agent = await get_agent_by_id(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent with ID {agent_id} not found")
        return {
            "data": format_agent_response(agent, {"created_at": agent.created_at.isoformat() if agent.created_at else None}),
            "meta": {"timestamp": datetime.now().isoformat()}
        }
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Exception in get_agent: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error getting agent: {str(e)}")


@router.put("/agents/{agent_id}")
async def update_agent_full(
    agent_id: str = Path(..., description="Agent ID"),
    agent_data: UpdateAgentRequest = None,
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("write")),
):
    """
    Update an agent (full update - replaces all fields)

    Gets owner_id (email) from Google Auth token to verify ownership.
    """
    try:
        owner_email = auth.get("user_id")
        auth_type = auth.get("auth_type")
        logger.info(f"Updating agent {agent_id} for owner_id (email) {owner_email}, auth_type: {auth_type}")

        agent = await get_agent_by_id(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent with ID {agent_id} not found")

        update_data = agent_data.model_dump(exclude_unset=False)
        updated_by = owner_email if auth_type == "session" else None  # only stamp actor on dashboard writes
        updated_agent = await update_agent_in_db(agent_id, update_data, updated_by=updated_by)
        if not updated_agent:
            raise HTTPException(status_code=500, detail="Failed to update agent")

        return {
            "data": format_agent_response(updated_agent),
            "meta": {"timestamp": datetime.now().isoformat(), "message": "Agent updated successfully"}
        }

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Exception in update_agent_full: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error updating agent: {str(e)}")


@router.patch("/agents/{agent_id}")
async def update_agent_partial(
    agent_id: str = Path(..., description="Agent ID"),
    agent_data: PatchAgentRequest = None,
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("write")),
):
    """
    Partially update an agent (only updates provided fields)

    Gets owner_id (email) from Google Auth token to verify ownership.
    """
    try:
        owner_email = auth.get("user_id")
        auth_type = auth.get("auth_type")
        logger.info(f"Partially updating agent {agent_id} for owner_id (email) {owner_email}, auth_type: {auth_type}")

        agent = await get_agent_by_id(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent with ID {agent_id} not found")

        update_data = agent_data.model_dump(exclude_unset=True)
        if not update_data:
            raise HTTPException(status_code=400, detail="No fields provided for update")

        updated_by = owner_email if auth_type == "session" else None  # only stamp actor on dashboard writes
        updated_agent = await update_agent_in_db(agent_id, update_data, updated_by=updated_by)
        if not updated_agent:
            raise HTTPException(status_code=500, detail="Failed to update agent")

        return {
            "data": format_agent_response(updated_agent),
            "meta": {"timestamp": datetime.now().isoformat(), "message": "Agent updated successfully"}
        }

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Exception in update_agent_partial: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error updating agent: {str(e)}")


@router.delete("/agents/{agent_id}")
async def delete_agent(
    agent_id: str = Path(..., description="Agent ID"),
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("delete")),
):
    """
    Delete an agent

    Gets owner_id (email) from Google Auth token to verify ownership.
    """
    try:
        owner_email = auth.get("user_id")
        auth_type = auth.get("auth_type")
        logger.info(f"Deleting agent {agent_id} for owner_id (email) {owner_email}, auth_type: {auth_type}")

        agent = await get_agent_by_id(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent with ID {agent_id} not found")

        # A demo agent is one row shown to every signed-in user, and it is listed
        # so that it renders in their own agent list - which means their UI offers
        # the usual delete control on something they do not own. Deleting it would
        # remove it for everybody, so only the account that actually owns it may.
        # Role checks are disabled for session callers (see agent/utils/
        # authorization.py), so without this there is nothing else in the way.
        if getattr(agent, "is_demo", False):
            real_owner = (getattr(agent, "owner_id", "") or "").lower()
            if auth_type == "session" and (owner_email or "").lower() != real_owner:
                logger.warning("[demo] delete refused: %s is not the owner of %s",
                               owner_email, agent_id)
                raise HTTPException(
                    status_code=403,
                    detail="This is a shared example agent and cannot be deleted.",
                )

        # owner_email is the acting user for session callers, None for master-key callers.
        deleted = await delete_agent_from_db(agent_id, deleted_by=owner_email)
        if not deleted:
            raise HTTPException(status_code=500, detail="Failed to delete agent")

        return {"message": "Agent deleted successfully", "meta": {"timestamp": datetime.now().isoformat()}}

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Exception in delete_agent: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error deleting agent: {str(e)}")
