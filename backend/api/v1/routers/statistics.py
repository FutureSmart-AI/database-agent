"""
RESTful API endpoints for agent statistics
Follows REST best practices with resource-based URLs
"""

from fastapi import APIRouter, HTTPException, Depends, Query
from starlette.requests import Request
from typing import Optional
from chatbot_management.utils.api_validation import get_api_key_or_session
from chatbot_management.services.logger import logger
import traceback
from agent.utils.authorization import require_agent_permission
from api.v1.utils.statistics_helper import get_agent_statistics_data


router = APIRouter(prefix="/v1")


@router.get("/agents/{agent_id}/statistics")
async def get_agent_statistics(
    agent_id: str,
    start_time: Optional[str] = Query(None, description="Start time for statistics (ISO format)"),
    end_time: Optional[str] = Query(None, description="End time for statistics (ISO format)"),
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("use")),
):
    """
    Get statistics for a specific agent

    """
    user_id = auth.get("user_id")
    logger.info(f"Getting statistics for agent_id: {agent_id}, user_id: {user_id}, start_time: {start_time}, end_time: {end_time}")

    try:
        result = await get_agent_statistics_data(agent_id, start_time, end_time)
        return {"data": result}

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error getting statistics for agent {agent_id}: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get statistics: {str(e)}"
        )
