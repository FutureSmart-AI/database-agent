"""
RESTful API endpoints for Feedback Management
Following REST best practices for managing agent feedback
"""
from typing import Optional

from fastapi import HTTPException, Depends, APIRouter, Path, Query
from pydantic import BaseModel, Field
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
        return await process_feedback(agent_id, body, auth=auth)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error submitting feedback: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


class AnswerReportRequest(BaseModel):
    session_id: str = Field(..., description="Conversation the answer belongs to")
    chat_id: str = Field(..., description="The answer being reported")
    category: str = Field(..., description="wrong_answer | wrong_chart | lost_context | error | slow | other")
    note: str = Field(..., description="What was wrong")
    expected: Optional[str] = Field(None, description="What the answer should have been")
    # Honoured only for master-key callers acting for a user, as on the chat route.
    user_id: Optional[str] = None


def _reporter(auth: dict, body_user: Optional[str]) -> str:
    if auth.get("auth_type") == "session":
        return (auth.get("user_id") or "").strip().lower()
    if auth.get("auth_type") == "master_api_key":
        return (body_user or "").strip().lower()
    return ""


@router.post("/agents/{agent_id}/reports")
async def report_answer_problem(
    body: AnswerReportRequest,
    agent_id: str = Path(..., description="Agent ID"),
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("use")),
):
    """Report a problem with one answer. The server attaches the conversation up to that
    answer, so the report can be reproduced; see chatbot_management/db_utils/answer_reports.py.
    Only the person who asked the question can report it."""
    from chatbot_management.db_utils.answer_reports import ReportError, create_report
    from chatbot_management.services.sqlmodel_session import async_session

    try:
        async with async_session() as session:
            report = await create_report(
                session, agent_id=agent_id, session_id=body.session_id, chat_id=body.chat_id,
                user_id=_reporter(auth, body.user_id), category=body.category, note=body.note,
                expected=body.expected)
    except ReportError as error:
        raise HTTPException(status_code=error.status, detail=error.message)
    logger.info(f"Answer report recorded | report_id={report['report_id']} agent_id={agent_id} "
                f"chat_id={body.chat_id} category={body.category}")
    return report


@router.get("/answer-reports")
async def list_answer_reports(
    agent_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    auth: dict = Depends(get_api_key_or_session),
):
    """Every reported answer problem, newest first, with its conversation snapshot
    (master key only: reports hold other people's questions)."""
    from chatbot_management.db_utils.answer_reports import list_reports
    from chatbot_management.services.sqlmodel_session import async_session

    if auth.get("auth_type") != "master_api_key":
        raise HTTPException(status_code=403, detail="Master key required")
    async with async_session() as session:
        return await list_reports(session, agent_id=agent_id, status=status, limit=limit)


class AnswerReportStatus(BaseModel):
    status: str = Field(..., description="open | triaged | fixed | not_a_bug")


@router.patch("/answer-reports/{report_id}")
async def update_answer_report(
    body: AnswerReportStatus,
    report_id: str = Path(...),
    auth: dict = Depends(get_api_key_or_session),
):
    """Move a report through triage (master key only)."""
    from chatbot_management.db_utils.answer_reports import ReportError, set_report_status
    from chatbot_management.services.sqlmodel_session import async_session

    if auth.get("auth_type") != "master_api_key":
        raise HTTPException(status_code=403, detail="Master key required")
    try:
        async with async_session() as session:
            found = await set_report_status(session, report_id, body.status)
    except ReportError as error:
        raise HTTPException(status_code=error.status, detail=error.message)
    if not found:
        raise HTTPException(status_code=404, detail="Report not found")
    return {"report_id": report_id, "status": body.status}
