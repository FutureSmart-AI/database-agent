import time
from datetime import datetime, timedelta
from chatbot_management.db_utils.common_db_utils import get_connection
from logger import logger
from sqlmodel import select, func
from sqlalchemy import Float, Integer
from models.sql_models import ChatLogs
from chatbot_management.services.sqlmodel_session import get_async_session

async def get_bot_statistics(chatbot_id=None, start_datetime=None, end_datetime=None, user_id=None, use_agent_id=False):
    """
    Get bot statistics.

    Args:
        chatbot_id: The chatbot/agent ID to filter by
        start_datetime: Start datetime for filtering
        end_datetime: End datetime for filtering
        user_id: User ID to filter by
        use_agent_id: If True, query using agent_id column (for new RESTful endpoints)
                     If False, query using chatbot_id column (for legacy endpoints)
    """
    try:
        # Validate and convert datetime parameters
        if start_datetime and isinstance(start_datetime, str):
            try:
                start_datetime = datetime.fromisoformat(start_datetime.replace('Z', '+00:00'))
            except ValueError:
                logger.warning(f"Invalid start_datetime format: {start_datetime}")
                start_datetime = None

        if end_datetime and isinstance(end_datetime, str):
            try:
                end_datetime = datetime.fromisoformat(end_datetime.replace('Z', '+00:00'))
            except ValueError:
                logger.warning(f"Invalid end_datetime format: {end_datetime}")
                end_datetime = None

        async for session in get_async_session():
            base = select(
                func.count().label("total_requests"),
                func.avg(func.cast(ChatLogs.gpt_response_time, Float)).label("avg_gpt_response_time"),
                func.avg(func.cast(ChatLogs.db_fetch_time, Float)).label("avg_db_fetch_time"),
                func.sum(func.cast(ChatLogs.tokens_consumed, Integer)).label("total_tokens_consumed"),
            )
            if chatbot_id:
                # Use agent_id column for new RESTful endpoints, chatbot_id for legacy
                if use_agent_id:
                    base = base.where(ChatLogs.agent_id == chatbot_id)
                else:
                    base = base.where(ChatLogs.chatbot_id == chatbot_id)
            if start_datetime and end_datetime and isinstance(start_datetime, datetime) and isinstance(end_datetime, datetime):
                try:
                    base = base.where(ChatLogs.created_at.between(start_datetime, end_datetime))
                except Exception as date_error:
                    logger.error(f"Error applying date filter: {date_error}")
                    # Skip date filtering if there's an issue
                    pass
            if user_id:
                base = base.where(ChatLogs.user_id == user_id)
            overall_res = await session.execute(base)
            overall_stats = overall_res.first()

            user_q = select(ChatLogs.user_id, func.count().label("request_count")).group_by(ChatLogs.user_id)
            if chatbot_id:
                # Use agent_id column for new RESTful endpoints, chatbot_id for legacy
                if use_agent_id:
                    user_q = user_q.where(ChatLogs.agent_id == chatbot_id)
                else:
                    user_q = user_q.where(ChatLogs.chatbot_id == chatbot_id)
            if start_datetime and end_datetime and isinstance(start_datetime, datetime) and isinstance(end_datetime, datetime):
                try:
                    user_q = user_q.where(ChatLogs.created_at.between(start_datetime, end_datetime))
                except Exception as date_error:
                    logger.error(f"Error applying date filter to user query: {date_error}")
                    # Skip date filtering if there's an issue
                    pass
            user_res = await session.execute(user_q)
            user_request_counts = [{"user_id": uid, "request_count": cnt} for uid, cnt in user_res.all()]

            # Select appropriate column for grouping
            bot_id_column = ChatLogs.agent_id if use_agent_id else ChatLogs.chatbot_id
            bot_q = select(bot_id_column, func.count().label("bot_request_count")).group_by(bot_id_column)
            if chatbot_id:
                # Use agent_id column for new RESTful endpoints, chatbot_id for legacy
                if use_agent_id:
                    bot_q = bot_q.where(ChatLogs.agent_id == chatbot_id)
                else:
                    bot_q = bot_q.where(ChatLogs.chatbot_id == chatbot_id)
            if start_datetime and end_datetime and isinstance(start_datetime, datetime) and isinstance(end_datetime, datetime):
                try:
                    bot_q = bot_q.where(ChatLogs.created_at.between(start_datetime, end_datetime))
                except Exception as date_error:
                    logger.error(f"Error applying date filter to bot query: {date_error}")
                    # Skip date filtering if there's an issue
                    pass
            bot_res = await session.execute(bot_q)
            # Use appropriate key name in response
            id_key = "agent_id" if use_agent_id else "chatbot_id"
            bot_request_counts = [{id_key: cid, "bot_request_count": cnt} for cid, cnt in bot_res.all()]

            return {
                "total_requests": overall_stats[0] if overall_stats else 0,
                "avg_gpt_response_time": overall_stats[1] if overall_stats else None,
                "avg_db_fetch_time": overall_stats[2] if overall_stats else None,
                "total_tokens_consumed": overall_stats[3] if overall_stats else 0,
                "user_request_counts": user_request_counts,
                "bot_request_counts": bot_request_counts,
            }
    except Exception as e:
        logger.error("Exception in get_bot_statistics:", e)
        return {"message": "Error in get_bot_statistics", "status": False}
