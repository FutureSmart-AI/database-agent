import pymysql
import aiomysql
import asyncio
import os
from datetime import time
# from common_postresql_utils import execute_sql_query, db_rows_affected_log
from sqlmodel import select
from models.sql_models import ChatLogs, Users, ChatbotInvitations, ChatbotDetails
from agent.services.sqlmodel_session import get_async_session
from datetime import datetime
from logger import logger


def get_connection():
    host = os.getenv("DB_HOST")
    user = os.getenv("DB_USER")
    password = os.getenv("DB_PASSWORD")
    db = os.getenv("DB_NAME")
    con = pymysql.connect(host=host, user=user, passwd=password, db=db, cursorclass=pymysql.cursors.DictCursor)
    return con

async def get_async_connection():
    # Replace with your actual database connection parameters
    port = os.getenv("DB_PORT")
    return await aiomysql.connect(
        host = os.getenv("DB_HOST"),
        user = os.getenv("DB_USER"),
        password = os.getenv("DB_PASSWORD"),
        db = os.getenv("DB_NAME"),
        port=int(port),
    )

async def upload_to_db_nl2sql_logs(
    session_id, user_id, chatbot_id, chat_id, query, refined_query,
    sql_query, db_output, response1, graph_output, gpt_response_time,
    db_fetch_time, tokens_consumed, is_graph_output, is_debug_mode,
    is_answered=None, debug_info=None, chart_output=None
):
    try:
        from agent.utils.common_utils import serialize_db_value

        # Normalize payload types to match models.ChatLogs
        # db_output column is a VARCHAR/Text → store as string
        if db_output is None:
            db_output_str = None
        elif isinstance(db_output, (dict, list, tuple)):
            import json as _json
            try:
                db_output_str = _json.dumps(serialize_db_value(db_output))
            except Exception:
                db_output_str = str(db_output)
        else:
            db_output_str = str(db_output)

        # graph_output column is JSON → store as dict.
        # Postgres JSON rejects NaN/Infinity, so sanitize before passing to asyncpg.
        graph_output_obj = None
        if graph_output is not None:
            if isinstance(graph_output, str):
                import json as _json
                try:
                    graph_output_obj = _json.loads(graph_output)
                except Exception:
                    # If it's a plain string, keep it as a JSON string value
                    graph_output_obj = {"value": graph_output}
            elif isinstance(graph_output, (dict, list)):
                graph_output_obj = graph_output
            else:
                graph_output_obj = {"value": str(graph_output)}

            graph_output_obj = serialize_db_value(graph_output_obj)

        # The built answer blocks, stored for later replay. JSON columns, so assign the
        # dict itself. serialize_db_value strips the Decimal/date/NaN values Postgres JSON
        # rejects — db_result carries real query output, so this is not optional.
        debug_info_obj = serialize_db_value(debug_info) if debug_info else None
        chart_output_obj = serialize_db_value(chart_output) if chart_output else None

        async for session in get_async_session():
            log = ChatLogs(
                session_id=session_id,
                user_id=user_id,
                agent_id=chatbot_id,  # Use agent_id as primary field
                chat_id=chat_id,
                user_query=query,
                refined_query=refined_query,
                sql_query=sql_query,
                db_output=db_output_str,
                gpt_response=response1,
                graph_output=graph_output_obj,
                gpt_response_time=str(gpt_response_time),
                db_fetch_time=str(db_fetch_time),
                tokens_consumed=str(tokens_consumed),
                debug_info=debug_info_obj,
                chart_output=chart_output_obj,
                is_graph_output=is_graph_output,
                is_debug_mode=is_debug_mode,
                is_answered=is_answered,
                created_at=datetime.utcnow()
            )
            session.add(log)
            await session.commit()
            return {"message": "Success: Inserted nl2sql_logs", "status": True}
    except Exception as e:
        logger.error(f"Exception in upload_to_db_nl2sql_logs: {str(e)}")
        return {"message": f"Error in upload_to_db_nl2sql_logs: {str(e)}", "status": False}
  
async def get_conversation(session_id):
    try:
        async for session in get_async_session():
            res = await session.execute(
                select(ChatLogs).where(ChatLogs.session_id == session_id)
            )
            logs = res.all()
            messages = []
            for log in logs:
                message_user = {"role": "user", "content": log.user_query}
                message_assistant = {"role": "assistant", "content": log.gpt_response}
                messages.extend([message_user, message_assistant])
            return messages
    except Exception as e:
        logger.error(f"Exception in get_conversation: {str(e)}")
        return {"message": f"Error in get_conversation: {str(e)}", "status": False}
    
# ----------------------
# Chat-related DB helpers
# ----------------------

async def get_user_email_from_id(user_id: str):
    """Get a user's email from their user_id using invitations table."""
    logger.info(f"[get_user_email_from_id] Entry: user_id={user_id}")
    try:
        async for session in get_async_session():
            res1 = await session.execute(
                select(ChatbotInvitations).where(
                    ChatbotInvitations.invited_user_email.like(f"{user_id}%")
                ).limit(1)
            )
            invitee = res1.first()
            if invitee:
                email = invitee.invited_user_email
                logger.info(f"[get_user_email_from_id] Found email for invitee: user_id={user_id}, email={email}")
                return email

            res2 = await session.execute(
                select(ChatbotInvitations).where(
                    ChatbotInvitations.invited_by_email.like(f"{user_id}%")
                ).limit(1)
            )
            inviter = res2.first()
            if inviter:
                email = inviter.invited_by_email
                logger.info(f"[get_user_email_from_id] Found email for inviter: user_id={user_id}, email={email}")
                return email
            return None
    except Exception as e:
        logger.error(f"[get_user_email_from_id] Error: {str(e)}", exc_info=True)
        return None


async def check_invitation_access(user_id: str, chatbot_id: str) -> bool:
    """Check if a user has access to a chatbot by checking the invitation table."""
    logger.info(f"[check_invitation_access] Entry: user_id={user_id}, chatbot_id={chatbot_id}")
    try:
        async for session in get_async_session():
            res_owner = await session.execute(
                select(ChatbotInvitations).where(
                    ChatbotInvitations.chatbot_id == chatbot_id,
                    ChatbotInvitations.invited_by_email.like(f"{user_id}%")
                ).limit(1)
            )
            if res_owner.first():
                logger.info(f"[check_invitation_access] User is owner: user_id={user_id}, chatbot_id={chatbot_id}")
                return True

            res_inv = await session.execute(
                select(ChatbotInvitations).where(
                    ChatbotInvitations.chatbot_id == chatbot_id,
                    ChatbotInvitations.invited_user_email.like(f"{user_id}%")
                ).limit(1)
            )
            invited = res_inv.first()
            if invited:
                logger.info(f"[check_invitation_access] User is invited: user_id={user_id}, chatbot_id={chatbot_id}, invited_user_email={invited.invited_user_email}")
                return True
            logger.warning(f"[check_invitation_access] User is not invited: user_id={user_id}, chatbot_id={chatbot_id}")
            return False
    except Exception as e:
        logger.error(f"[check_invitation_access] Error: {str(e)}", exc_info=True)
        return False


async def check_direct_chatbot_access(chatbot_id: str, user_email: str | None = None, user_id: str | None = None) -> bool:
    """Directly check access from chatbot_details and chatbot_invitations."""
    logger.info(f"[check_direct_chatbot_access] Entry: chatbot_id={chatbot_id}, user_id={user_id}, user_email={user_email}")
    try:
        async for session in get_async_session():
            if user_id:
                res_owner = await session.execute(
                    select(ChatbotDetails).where(
                        ChatbotDetails.chatbot_id == chatbot_id,
                        ChatbotDetails.user_id == user_id,
                        ChatbotDetails.deleted != True
                    ).limit(1)
                )
                if res_owner.first():
                    logger.info(f"[check_direct_chatbot_access] User is owner: user_id={user_id}, chatbot_id={chatbot_id}")
                    return True

            if user_email:
                res_inv_email = await session.execute(
                    select(ChatbotInvitations).where(
                        ChatbotInvitations.chatbot_id == chatbot_id,
                        ChatbotInvitations.invited_user_email == user_email
                    ).limit(1)
                )
                if res_inv_email.first():
                    logger.info(f"[check_direct_chatbot_access] User is invited by email: user_email={user_email}, chatbot_id={chatbot_id}")
                    return True

            if user_id and not user_email:
                res_inv_id = await session.execute(
                    select(ChatbotInvitations).where(
                        ChatbotInvitations.chatbot_id == chatbot_id,
                        ChatbotInvitations.invited_user_email.like(f"{user_id}%")
                    ).limit(1)
                )
                if res_inv_id.first():
                    logger.info(f"[check_direct_chatbot_access] User is invited by id: user_id={user_id}, chatbot_id={chatbot_id}")
                    return True

            logger.warning(f"[check_direct_chatbot_access] User not authorized: chatbot_id={chatbot_id}, user_id={user_id}, user_email={user_email}")
            return False
    except Exception as e:
        logger.error(f"[check_direct_chatbot_access] Error: {str(e)}", exc_info=True)
        return False


async def get_owner_user_id_by_chatbot_id(chatbot_id: str) -> str | None:
    """Fetch the owner's user_id for a given chatbot_id from chatbot_details."""
    logger.info(f"[get_owner_user_id_by_chatbot_id] Entry: chatbot_id={chatbot_id}")
    try:
        async for session in get_async_session():
            res = await session.execute(
                select(ChatbotDetails.user_id).where(
                    ChatbotDetails.chatbot_id == chatbot_id,
                    ChatbotDetails.deleted != True
                ).limit(1)
            )
            row = res.first()
            if row:
                user_id_val = row if isinstance(row, str) else (row[0] if isinstance(row, tuple) else getattr(row, "user_id", None))
                logger.info(f"[get_owner_user_id_by_chatbot_id] Owner found: chatbot_id={chatbot_id}, user_id={user_id_val}")
                return user_id_val
            logger.warning(f"[get_owner_user_id_by_chatbot_id] No owner found for chatbot_id={chatbot_id}")
            return None
    except Exception as e:
        logger.error(f"[get_owner_user_id_by_chatbot_id] Error: {str(e)}", exc_info=True)
        return None
                