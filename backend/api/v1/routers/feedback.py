"""
RESTful API endpoints for Feedback Management
Following REST best practices for managing agent feedback
"""
from fastapi import HTTPException, Depends, APIRouter, Path
from starlette.requests import Request
from chatbot_management.utils.api_validation import get_api_key_or_session
from chatbot_management.services.logger import logger
import traceback

# Import schemas from centralized location
from api.v1.schemas.feedback import FeedbackRequest
from agent.utils.authorization import require_agent_permission
from api.v1.utils.feedback_helper import process_feedback

router = APIRouter(prefix="/v1")


@router.post("/agents/{agent_id}/feedback")
async def submit_feedback(
    agent_id: str = Path(..., description="Agent ID"),
    body: FeedbackRequest = None,
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("use")),
):
    """
    Submit feedback on agent responses

    """
    try:
        return await process_feedback(agent_id, body)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error submitting feedback: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
