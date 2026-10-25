"""
Business logic for feedback management
"""
from typing import Optional

from fastapi import HTTPException
from chatbot_management.services.logger import logger


async def verify_agent_exists(agent_id: str) -> None:
    from models.sql_models import ChatbotDetails
    from chatbot_management.services.sqlmodel_session import get_async_session
    from sqlmodel import select

    async for session in get_async_session():
        result = await session.execute(
            select(ChatbotDetails).where(ChatbotDetails.agent_id == agent_id)
        )
        agent = result.scalar_one_or_none()
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")


async def _demo_visitor(agent_id: str, auth: Optional[dict]) -> Optional[str]:
    """The visitor's user id when this feedback is on a shared demo agent from anyone but its
    owner, else None. See chatbot_management/db_utils/demo_allowance.demo_question_user."""
    from models.sql_models import ChatbotDetails
    from chatbot_management.services.sqlmodel_session import get_async_session
    from chatbot_management.db_utils.demo_allowance import demo_question_user
    from sqlmodel import select

    if not auth:
        return None
    async for session in get_async_session():
        agent = (await session.execute(
            select(ChatbotDetails).where(ChatbotDetails.agent_id == agent_id))).scalar_one_or_none()
        return demo_question_user(agent, auth.get("auth_type"), auth.get("user_id"))
    return None


async def _asked_by(session_id: str, chat_id: str, agent_id: str, user_id: str) -> bool:
    from models.sql_models import ChatLogs
    from chatbot_management.services.sqlmodel_session import get_async_session
    from sqlmodel import select

    async for session in get_async_session():
        row = (await session.execute(select(ChatLogs.user_id).where(
            ChatLogs.session_id == session_id, ChatLogs.chat_id == chat_id,
            ChatLogs.agent_id == agent_id))).first()
        return bool(row) and (row[0] or "").strip().lower() == user_id
    return False


async def process_feedback(agent_id: str, body, auth: Optional[dict] = None) -> dict:
    from session.db_utils.session_db_utils import add_user_feedback
    from knowledge.utils.few_shot_utils import get_few_shot_service

    await verify_agent_exists(agent_id)

    # A shared demo agent is used by everyone. A visitor's feedback is recorded on their own
    # answer only, and never changes the agent: no SQL they send replaces the stored query and
    # none becomes a few-shot example every other visitor's questions would then follow.
    visitor = await _demo_visitor(agent_id, auth)
    if visitor is not None:
        if not visitor or not await _asked_by(body.session_id, body.chat_id, agent_id, visitor):
            raise HTTPException(status_code=403,
                                detail="You can only give feedback on your own answers.")
        body.corrected_query = None

    logger.info(f"Feedback submission for agent {agent_id}, session {body.session_id}, chat {body.chat_id}")

    if body.label not in ["correct", "incorrect", "accepted", "rejected"]:
        raise HTTPException(
            status_code=400,
            detail="Invalid label. Must be 'correct', 'incorrect', 'accepted', or 'rejected'"
        )

    normalized_label = body.label
    if body.label == "correct":
        normalized_label = "accepted"
    elif body.label == "incorrect":
        normalized_label = "rejected"

    # Every feedback call wrote the caller's SQL over the stored query. On a demo agent the
    # stored query is the record of what the agent actually ran (answer reports read it), so a
    # visitor's feedback records the verdict only.
    sql_to_store = None if visitor is not None else (
        body.corrected_query
        if normalized_label == "rejected" and body.corrected_query
        else body.generated_query
    )

    await add_user_feedback(
        session_id=body.session_id,
        chat_id=body.chat_id,
        feedback=normalized_label,
        corrected_sql=sql_to_store,
        agent_id=agent_id,
    )

    if normalized_label == "rejected" and body.corrected_query:
        logger.info(f"Adding corrected query to few-shot examples: {body.corrected_query}")
        try:
            few_shot_service = await get_few_shot_service()
            example = {
                "id": body.user_query,
                "question": body.user_query,
                "sql_query": body.corrected_query
            }
            # Embedding the correction is paid for by the agent owner's key policy.
            from agent.utils.provider_key_scope import owner_key_scope
            from chatbot_management.db_utils.bot_crud_db_utils import get_owner_email_by_agent_id
            async with owner_key_scope(await get_owner_email_by_agent_id(agent_id)):
                await few_shot_service.add_example(None, agent_id, example)
            logger.info("Successfully added corrected query to few-shot examples")
        except Exception as e:
            logger.error(f"Error adding to few-shot examples: {str(e)}")

    return {"status": "success", "message": "Feedback recorded"}
