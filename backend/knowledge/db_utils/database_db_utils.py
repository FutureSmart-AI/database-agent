import pymysql
import aiomysql
import asyncio
import os
from datetime import time
from sqlmodel import select
from knowledge.services.sqlmodel_session import get_async_session
from models.sql_models import ChatbotConnection
from datetime import datetime
from knowledge.services.logger import logger
from database_connection.source_connection import open_source_connection


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
    
def _connection_to_details(record: ChatbotConnection) -> dict:
    return {
        "db_id": record.db_id,
        "db_host": record.db_host,
        "db_name": record.db_name,
        "db_user": record.db_user,
        "db_password": record.db_password,
        "db_port": record.db_port,
        "db_engine": record.db_engine,
    }


async def get_db_connection(user_id: str, agent_id: str, db_id: str = None):
    """
    Get a single database connection for an agent.

    Multi-DB: if `db_id` is given, return that specific database; otherwise return the
    agent's primary (oldest active) connection, preserving legacy single-DB behaviour.

    Returns:
        dict: Response with status, message, and db_details
    """
    try:
        async for session in get_async_session():
            if db_id:
                query = select(ChatbotConnection).where(
                    ChatbotConnection.db_id == db_id,
                    ChatbotConnection.deleted == False,  # noqa: E712 — never use a detached DB
                )
            else:
                query = select(ChatbotConnection).where(
                    (ChatbotConnection.agent_id == agent_id) | (ChatbotConnection.chatbot_id == agent_id),
                    ChatbotConnection.deleted == False,  # noqa: E712
                ).order_by(ChatbotConnection.is_active.desc(), ChatbotConnection.created_at)
            record = (await session.execute(query)).scalars().first()

            if record:
                try:
                    db_details = _connection_to_details(record)
                    logger.info(f"Successfully retrieved database connection for agent_id: {agent_id} (db_id={record.db_id})")
                    return {"status": True, "message": "Database connection retrieved successfully", "db_details": db_details}
                except Exception as e:
                    logger.error(f"Error parsing database connection details: {str(e)}")
                    return {"status": False, "error": str(e), "db_details": None}
            else:
                logger.warning(f"No database connection found for agent_id: {agent_id}")
                return {
                    "status": False,
                    "message": f"No database connection configured for agent_id: {agent_id}. Please set up a database connection first.",
                    "db_details": None
                }
    except Exception as e:
        logger.error(f"Error getting database connection for agent_id {agent_id}: {str(e)}")
        return {"status": False, "message": f"Error retrieving database connection: {str(e)}", "db_details": None}


async def get_db_connection_by_id(agent_id: str, db_id: str):
    """Return one specific database by db_id."""
    return await get_db_connection(None, agent_id, db_id=db_id)


async def get_primary_db_id(agent_id: str):
    """Resolve an agent's primary db_id (oldest active connection)."""
    try:
        async for session in get_async_session():
            record = (await session.execute(
                select(ChatbotConnection)
                .where(
                    (ChatbotConnection.agent_id == agent_id) | (ChatbotConnection.chatbot_id == agent_id),
                    ChatbotConnection.deleted == False,  # noqa: E712 — a tombstone is never primary
                )
                .order_by(ChatbotConnection.is_active.desc(), ChatbotConnection.created_at)
            )).scalars().first()
            return record.db_id if record else None
    except Exception as e:
        logger.error(f"Error in get_primary_db_id for agent_id {agent_id}: {str(e)}")
        return None

async def get_all_tables(db_details):
    """Get all table names from the database."""
    try:
        if db_details['db_engine'] == 'mysql':
            conn = open_source_connection(db_details)
            try:
                with conn.cursor() as cursor:
                    cursor.execute("SHOW TABLES")
                    tables = [table[0] for table in cursor.fetchall()]
            finally:
                conn.close()

        elif db_details['db_engine'] == 'postgresql':
            conn = open_source_connection(db_details)
            try:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT table_name 
                        FROM information_schema.tables 
                        WHERE table_schema='public' AND table_type='BASE TABLE'
                    """)
                    tables = [table[0] for table in cursor.fetchall()]
            finally:
                conn.close()

        else:
            raise ValueError(f"Unsupported database engine: {db_details['db_engine']}")

        return tables
    except Exception as e:
        logger.error(f"Error getting tables from database: {str(e)}")
        raise


async def get_table_columns(db_details, table_name):
        """Get all column names for a given table in the database.

        Args:
            db_details: dict with keys `db_engine`, `db_host`, `db_user`, `db_password`, `db_name`
            table_name: name of the table to inspect

        Returns:
            list of column names (strings)
        """
        try:
            engine = db_details.get('db_engine')
            if engine == 'mysql':
                conn = open_source_connection(db_details)
                try:
                    with conn.cursor() as cursor:
                        cursor.execute(f"SHOW COLUMNS FROM `{table_name}`")
                        rows = cursor.fetchall()
                        if rows:
                            if isinstance(rows[0], dict):
                                cols = [r.get('Field') for r in rows]
                            else:
                                cols = [r[0] for r in rows]
                            logger.info(f"Columns for table {table_name}: {cols}")
                            return cols
                        return []
                finally:
                    conn.close()
                        

            elif engine == 'postgresql':
                conn = open_source_connection(db_details)
                try:
                    with conn.cursor() as cursor:
                        cursor.execute(
                            """
                            SELECT column_name
                            FROM information_schema.columns
                            WHERE table_schema = 'public' AND table_name = %s
                            ORDER BY ordinal_position
                            """,
                            (table_name,)
                        )
                        rows = cursor.fetchall()
                        cols = [r[0] for r in rows]
                        logger.info(f"Columns for table {table_name}: {cols}")
                        return cols
                finally:
                    conn.close()

            else:
                raise ValueError(f"Unsupported database engine: {engine}")

        except Exception as e:
            logger.error(f"Error getting columns for table {table_name}: {str(e)}")
            raise