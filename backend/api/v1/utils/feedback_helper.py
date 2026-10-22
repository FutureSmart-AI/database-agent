"""
Business logic for feedback management
"""
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


async def process_feedback(agent_id: str, body) -> dict:
    from session.db_utils.session_db_utils import add_user_feedback
    from knowledge.utils.few_shot_utils import get_few_shot_service

    await verify_agent_exists(agent_id)

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

    sql_to_store = (
        body.corrected_query
        if normalized_label == "rejected" and body.corrected_query
        else body.generated_query
    )

    await add_user_feedback(
        session_id=body.session_id,
        chat_id=body.chat_id,
        feedback=normalized_label,
        corrected_sql=sql_to_store
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
            await few_shot_service.add_example(None, agent_id, example)
            logger.info("Successfully added corrected query to few-shot examples")
        except Exception as e:
            logger.error(f"Error adding to few-shot examples: {str(e)}")

    return {"status": "success", "message": "Feedback recorded"}
