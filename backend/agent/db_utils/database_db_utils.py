import pymysql
import psycopg2

import time
import uuid
from datetime import datetime, timedelta
from agent.db_utils.common_postresql_utils import execute_sql_query, db_rows_affected_log

from logger import logger

from sqlmodel import select
from models.sql_models import ChatbotConnection
from agent.services.sqlmodel_session import get_async_session
from datetime import datetime
from typing import List, Optional, Dict, Any
import os
from otel_tracing import track_time


def generate_db_id() -> str:
    """Generate a new database identifier (DB_<8hex>), matching the NL2SQL_ convention."""
    return f"DB_{str(uuid.uuid4()).split('-')[0]}".upper()


def _connection_to_details(connection: ChatbotConnection) -> Dict[str, Any]:
    """Map a ChatbotConnection row to the runtime db_details dict used by the pipeline."""
    return {
        "db_id": connection.db_id,
        "db_host": connection.db_host,
        "db_name": connection.db_name,
        "db_user": connection.db_user,
        "db_password": connection.db_password,
        "db_port": connection.db_port,
        "db_engine": connection.db_engine,
    }


@track_time("DB: Get DB Connection")
async def get_db_connection(user_id, agent_id, db_id: Optional[str] = None):
    """
    Get a single database connection for an agent.

    Multi-DB: if `db_id` is given, return that specific database. Otherwise return the
    agent's PRIMARY database (falling back to the first active one), preserving the legacy
    single-DB behaviour for callers that haven't been updated yet.

    Returns:
        dict: {status, message, db_details}
    """
    try:
        async for session in get_async_session():
            if db_id:
                query = select(ChatbotConnection).where(
                    ChatbotConnection.db_id == db_id,
                    ChatbotConnection.deleted == False,  # noqa: E712 — never connect to a detached DB
                )
            else:
                # primary first, then any active, then any row — for the agent or legacy chatbot_id
                # Primary = oldest active DB (no explicit flag).
                query = select(ChatbotConnection).where(
                    (ChatbotConnection.agent_id == agent_id) | (ChatbotConnection.chatbot_id == agent_id),
                    ChatbotConnection.deleted == False,  # noqa: E712
                ).order_by(ChatbotConnection.is_active.desc(), ChatbotConnection.created_at)

            res = await session.execute(query)
            connection = res.scalars().first()
            if connection:
                if not all([connection.db_host, connection.db_name, connection.db_user, connection.db_engine]):
                    logger.error(f"Incomplete database connection details for agent_id: {agent_id}")
                    return {
                        "status": False,
                        "message": f"Database connection is incomplete for agent_id: {agent_id}. Please configure all required fields (host, name, user, engine).",
                        "db_details": None,
                    }
                details = _connection_to_details(connection)
                logger.info(f"Successfully retrieved database connection for agent_id: {agent_id} (db_id={connection.db_id})")
                return {"status": True, "message": "Database connection retrieved successfully", "db_details": details}
            else:
                logger.warning(f"No database connection found for agent_id: {agent_id}")
                return {
                    "status": False,
                    "message": f"No database connection configured for agent_id: {agent_id}. Please set up a database connection first.",
                    "db_details": None,
                }
    except Exception as e:
        logger.error(f"Exception in get_db_connection for agent_id {agent_id}: {str(e)}")
        return {"status": False, "message": f"Error retrieving database connection: {str(e)}", "db_details": None}


async def get_db_connection_by_id(agent_id, db_id):
    """Convenience wrapper returning one specific database by db_id."""
    return await get_db_connection(None, agent_id, db_id=db_id)


async def get_primary_db_id(agent_id: str) -> Optional[str]:
    """Resolve an agent's primary db_id (primary flag first, else first active, else any)."""
    try:
        async for session in get_async_session():
            res = await session.execute(
                select(ChatbotConnection)
                .where(
                    (ChatbotConnection.agent_id == agent_id) | (ChatbotConnection.chatbot_id == agent_id),
                    ChatbotConnection.deleted == False,  # noqa: E712 — a tombstone is never primary
                )
                .order_by(ChatbotConnection.is_active.desc(), ChatbotConnection.created_at)
            )
            connection = res.scalars().first()
            return connection.db_id if connection else None
    except Exception as e:
        logger.error(f"Exception in get_primary_db_id for agent_id {agent_id}: {str(e)}")
        return None


async def get_all_databases(agent_id: str, active_only: bool = True) -> List[Dict[str, Any]]:
    """
    Return all databases for an agent as routing/execution dicts (credentials included).
    Each item: {db_id, description, is_active, ...db_details}.
    """
    out: List[Dict[str, Any]] = []
    try:
        async for session in get_async_session():
            query = select(ChatbotConnection).where(
                (ChatbotConnection.agent_id == agent_id) | (ChatbotConnection.chatbot_id == agent_id),
                ChatbotConnection.deleted == False,  # noqa: E712 — excluded from routing/execution
            )
            if active_only:
                query = query.where(ChatbotConnection.is_active == True)  # noqa: E712
            query = query.order_by(ChatbotConnection.is_active.desc(), ChatbotConnection.created_at)
            res = await session.execute(query)
            for connection in res.scalars().all():
                item = _connection_to_details(connection)
                item.update({
                    "description": connection.description,
                    "is_active": bool(connection.is_active),
                })
                out.append(item)
    except Exception as e:
        logger.error(f"Exception in get_all_databases for agent_id {agent_id}: {str(e)}")
    return out
