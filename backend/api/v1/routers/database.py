"""
RESTful API endpoints for Database Connection Management
Following REST best practices for managing agent database connections
"""
import asyncio
from typing import Optional, Set

from fastapi import HTTPException, Depends, APIRouter, Path
from starlette.requests import Request
from chatbot_management.utils.api_validation import get_api_key_or_session
from chatbot_management.services.logger import logger
import traceback
from database_connection.utils.exceptions import DatabaseConnectionError

# Import schemas from centralized location
from api.v1.schemas.database import (
    DatabaseConnectionResponse,
    DatabaseConnectionRequest,
    TestDatabaseConnectionRequest,
)
from agent.utils.authorization import require_agent_permission
from api.v1.utils.database_helper import (
    get_agent_database_connection, update_agent_database_connection, test_raw_database_connection
)

router = APIRouter(prefix="/v1")

# Strong references prevent background tasks from being GC'd before they complete
_hc_background_tasks: Set[asyncio.Task] = set()


async def _run_hc_profiling_background(agent_id: str, user_id: Optional[str], db_id: Optional[str] = None) -> None:
    """Auto-profile HC columns after DB credentials are saved. Runs as a background task.

    Multi-DB: when `db_id` is given, profiling and Qdrant indexing are scoped to that
    specific database; otherwise it targets the agent's primary DB.
    """
    try:
        logger.info(f"[HC Auto-Profile] Starting background profiling for agent {agent_id} (db_id={db_id})")
        from knowledge.db_utils.hc_profile_db_utils import delete_hc_column_profiles
        await delete_hc_column_profiles(agent_id, db_id=db_id)
        from api.v1.routers.hc_profile import run_hc_profile_for_agent
        from api.v1.schemas.hc_profile import TriggerHCProfileRequest
        await run_hc_profile_for_agent(user_id, agent_id, TriggerHCProfileRequest(auto_register_hc=True), db_id=db_id)
        logger.info(f"[HC Auto-Profile] Background profiling completed for agent {agent_id}")
    except Exception as e:
        logger.error(f"[HC Auto-Profile] Background profiling failed for agent {agent_id}: {e}")


@router.get("/agents/{agent_id}/database-connection")
async def get_database_connection(
    agent_id: str = Path(..., description="Agent ID"),
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("edit_agent")),
):
    """
    Get database connection details for an agent
    """
    try:
        user_id = auth.get("user_id")
        logger.info(f"Received request for /agents/{agent_id}/database-connection, user_id={user_id}")
        return await get_agent_database_connection(agent_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting database connection: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.put("/agents/{agent_id}/database-connection")
async def update_database_connection(
    agent_id: str = Path(..., description="Agent ID"),
    body: DatabaseConnectionRequest = None,
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("edit_agent")),
):
    """
    Update database connection for an agent
    """
    try:
        user_id = auth.get("user_id")
        logger.info(f"Received request for /agents/{agent_id}/database-connection for input: {body}, user_id={user_id}")

        result = await update_agent_database_connection(agent_id, body)

        if result.get("db_changed"):
            owner_id = result.get("owner_id", user_id)
            task = asyncio.create_task(_run_hc_profiling_background(agent_id, owner_id))
            _hc_background_tasks.add(task)
            task.add_done_callback(_hc_background_tasks.discard)
            logger.info(f"[HC Auto-Profile] DB identity changed — background profiling scheduled for agent {agent_id}")
        else:
            logger.info(f"[HC Auto-Profile] No DB identity change — skipping re-profiling for agent {agent_id}")

        return {"message": result.get("message", f"Database connection updated successfully for {agent_id}")}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating database connection: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/database-connections/test")
async def test_database_connection_endpoint(
    body: TestDatabaseConnectionRequest = None,
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session)
):
    """
    Test a database connection without associating it with an agent

    This endpoint allows you to verify database credentials before creating or updating an agent.
    """
    try:
        user_id = auth.get("user_id")
        logger.info(f"Received request for /database-connections/test, user_id={user_id}")
        return await test_raw_database_connection(body)
    except HTTPException as e:
        raise e
    except DatabaseConnectionError as e:
        logger.error(f"Database connection error: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"An error occurred: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal Server Error")
