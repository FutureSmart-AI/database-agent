"""
RESTful API endpoints for Session Management
Following REST best practices for managing agent chat sessions
"""
from fastapi import HTTPException, Depends, APIRouter, Path, Query
from chatbot_management.utils.common import extract_user_from_email
from starlette.requests import Request
from chatbot_management.utils.api_validation import get_api_key_or_session
from chatbot_management.services.logger import logger
import traceback
from typing import Optional
from datetime import datetime

# Import session database utilities
from session.db_utils.session_db_utils import (
    retrieve_sessions,
    get_session_details,
    get_session_data,
    add_session_title_to_db,
    mark_session_as_deleted
)

# Import schemas from centralized location
from api.v1.schemas.sessions import (
    SessionResponse,
    SessionListResponse,
    SessionDetailResponse,
    UpdateSessionRequest,
)
from agent.utils.authorization import require_agent_permission
from api.v1.utils.chat_helper import get_agent_with_visibility

router = APIRouter(prefix="/v1")


@router.get("/agents/{agent_id}/sessions")
async def get_agent_sessions(
    agent_id: str = Path(..., description="Agent ID"),
    show_guests_session: bool = Query(False, description="Include guest sessions (owner only)"),
    email: Optional[str] = Query(None, description="Filter by email"),
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("use")),
):
    """
    Get all sessions for a specific agent

    Returns a list of chat sessions associated with the agent.
    - If authenticated, returns sessions for the authenticated user
    - If `show_guests_session=true` and user is owner, includes guest sessions
    """
    try:
        # Get authenticated user details from the dependency
        auth_type = auth.get("auth_type")
        auth_email = auth.get("user_id") # Email if session, None if master key
        resolved_user_id = None

        if auth_type == "session":
            session_data = auth.get("session_data", {})
            resolved_user_id = await extract_user_from_email({
                "email": auth_email,
                "user_id": session_data.get("user_id"),
                "all_claims": session_data.get("all_claims", {})
            })

            # If email param is provided that doesn't match authenticated email, block
            if email and email.lower() != (auth_email or "").lower():
                raise HTTPException(
                    status_code=403,
                    detail="You can only fetch your own sessions"
                )
            email = auth_email
        else:
            # Master API key access
            # email stays as provided or None
            pass
        
        logger.info(
            f"Getting sessions for agent {agent_id}, user_id={resolved_user_id}, "
            f"email={email}, show_guests_session={show_guests_session}"
        )

        # Retrieve sessions from database
        response = await retrieve_sessions(
            user_id=resolved_user_id,
            agent_id=agent_id,
            show_guests_session=show_guests_session,
            email=email
        )
        
        if response is None:
            return {
                "sessions": [],
                "meta": {
                    "timestamp": datetime.now().isoformat(),
                    "message": "No sessions found"
                }
            }
        
        return {
            "sessions": response,
            "meta": {
                "timestamp": datetime.now().isoformat(),
                "total": len(response)
            }
        }
        
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error getting sessions for agent {agent_id}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error retrieving sessions: {str(e)}")


@router.get("/agents/{agent_id}/sessions/{session_id}")
async def get_session(
    agent_id: str = Path(..., description="Agent ID"),
    session_id: str = Path(..., description="Session ID"),
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("use")),
):
    """
    Get a specific session by ID with conversation data

    Returns session details including:
    - Session metadata (title, created time)
    - Full conversation history
    """
    try:
        # user_id is extracted from auth but not strictly used for filtering here
        resolved_user_id = auth.get("user_id")
        
        logger.info(
            f"Getting session {session_id} for agent {agent_id}, user_id={resolved_user_id}"
        )

        # Get session details
        session_details = await get_session_details(session_id=session_id, agent_id=agent_id)
        
        if not session_details:
            raise HTTPException(
                status_code=404,
                detail=f"Session {session_id} not found for agent {agent_id}"
            )
        
        # Get conversation data, under the agent's answer visibility settings
        _, show_sql_query, show_db_result, _ = await get_agent_with_visibility(agent_id)
        conversation_data = await get_session_data(
            session_id, agent_id=agent_id, show_sql_query=show_sql_query, show_db_result=show_db_result)
        
        return {
            "session_id": session_details['session_id'],
            "session_title": session_details['session_title'],
            "created_time": session_details['created_time'],
            "conversation_data": conversation_data or [],
            "meta": {
                "timestamp": datetime.now().isoformat()
            }
        }
        
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error getting session {session_id}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error retrieving session: {str(e)}")


@router.patch("/agents/{agent_id}/sessions/{session_id}")
async def update_session(
    agent_id: str = Path(..., description="Agent ID"),
    session_id: str = Path(..., description="Session ID"),
    session_data: UpdateSessionRequest = None,
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("use")),
):
    """
    Update a session (partial update)

    Currently supports updating:
    - session_title: Update the session title
    """
    try:
        # user_id is extracted from auth but not strictly used for filtering here
        resolved_user_id = auth.get("user_id")
        
        logger.info(
            f"Updating session {session_id} for agent {agent_id}, user_id={resolved_user_id}"
        )

        # Verify session exists
        session_details = await get_session_details(session_id=session_id, agent_id=agent_id)

        if not session_details:
            raise HTTPException(
                status_code=404,
                detail=f"Session {session_id} not found for agent {agent_id}"
            )

        # Update session title if provided
        if session_data.session_title is not None:
            # resolved_user_id is the acting user for session callers, None for master-key callers.
            await add_session_title_to_db(session_id, session_data.session_title, updated_by=resolved_user_id)
            logger.info(f"Updated session title for {session_id}")

        # Get updated session details
        updated_session = await get_session_details(session_id=session_id, agent_id=agent_id)
        
        return {
            "data": {
                "session_id": updated_session['session_id'],
                "session_title": updated_session['session_title'],
                "created_time": updated_session['created_time']
            },
            "meta": {
                "timestamp": datetime.now().isoformat(),
                "message": "Session updated successfully"
            }
        }
        
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error updating session {session_id}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error updating session: {str(e)}")


@router.delete("/agents/{agent_id}/sessions/{session_id}")
async def delete_session(
    agent_id: str = Path(..., description="Agent ID"),
    session_id: str = Path(..., description="Session ID"),
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("use")),
):
    """
    Delete a session (soft delete)

    Marks the session as deleted in the database.
    The session data is not physically removed.
    """
    try:
        # user_id is extracted from auth but not strictly used for filtering here
        resolved_user_id = auth.get("user_id")
        
        logger.info(
            f"Deleting session {session_id} for agent {agent_id}, user_id={resolved_user_id}"
        )

        # Verify session exists before deletion
        session_details = await get_session_details(session_id=session_id, agent_id=agent_id)

        if not session_details:
            raise HTTPException(
                status_code=404,
                detail=f"Session {session_id} not found for agent {agent_id}"
            )

        # Mark session as deleted
        # resolved_user_id doubles as the ownership filter and the acting user here
        # (None for master-key callers, which leaves deleted_by NULL).
        success = await mark_session_as_deleted(
            session_id=session_id, user_id=resolved_user_id, agent_id=agent_id,
            deleted_by=resolved_user_id,
        )
        
        if not success:
            raise HTTPException(
                status_code=500,
                detail="Failed to delete session"
            )
        
        return {
            "message": "Session deleted successfully",
            "meta": {
                "timestamp": datetime.now().isoformat(),
                "session_id": session_id
            }
        }
        
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error deleting session {session_id}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error deleting session: {str(e)}")


