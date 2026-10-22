from logger import logger
import asyncpg
import asyncio
import os

from sqlmodel import select
from agent.services.sqlmodel_session import get_async_session
from models.sql_models import ChatbotDetails, ChatbotInvitations
from otel_tracing import track_time

global pool

async def init_db_pool():
    """Initialize the database connection pool."""
    global pool
    if 'pool' not in globals():
        pool = await asyncpg.create_pool(
            user=os.getenv("POSTGRES_USER"),
            password=os.getenv("POSTGRES_PASSWORD"),
            database=os.getenv("POSTGRES_DB_NAME"),
            host=os.getenv("POSTGRES_HOST"),
            port=os.getenv("POSTGRES_PORT"),
            min_size=10,
            max_size=40
        )
        logger.info("Database connection pool created")
    else:
        logger.info("Database connection pool reused")
    return pool

async def get_connection_pool():
    """Returns the database connection pool, initializing it if necessary."""
    global pool
    if 'pool' not in globals():
        pool = await init_db_pool()
    return pool    

@track_time("DB: Execute SQL Query")
async def execute_sql_query(query, *args, fetchone=False, fetchall=False, fetchval=False):
    """Executes a SQL query using the async connection pool with retry logic."""
    global pool
    if 'pool' not in globals():
        pool = await init_db_pool()

    retries = 0
    MAX_RETRIES = 3
    RETRY_DELAY = 2
    while retries < MAX_RETRIES:
        try:
            async with pool.acquire() as conn:
                if fetchone:
                    return await conn.fetchrow(query, *args)
                elif fetchall:
                    return await conn.fetch(query, *args)
                elif fetchval:
                    return await conn.fetchval(query, *args)
                else:
                    return await conn.execute(query, *args)
        except asyncpg.exceptions.TooManyConnectionsError:
            logger.warning(f"Connection pool exhausted. Retrying {retries+1}/{MAX_RETRIES}...")
            retries += 1
            await asyncio.sleep(RETRY_DELAY)
        except asyncpg.exceptions.PostgresConnectionError as e:
            logger.error(f"Database connection error: {e}")
            break
        except Exception as e:
            logger.error(f"Unexpected database error: {e}")
            break
    logger.error("Failed to execute query after multiple retries.")
    return None

async def close_db_pool():
    """Close the database connection pool."""
    global pool
    if 'pool' not in globals():
        await init_db_pool()
    if pool:
        await pool.close()


def db_rows_affected_log(row_affected: str, success_message: str, error_message: str):
    try:
        # Extract the number of rows affected for Update, Delete, Insert queries
        row_affected = int(row_affected.split()[-1]) 
        if row_affected == 0:
            logger.error(f"Rows affected: {row_affected}. {error_message}")
        else:
            logger.info(f"Rows affected: {row_affected}. {success_message}")
    except Exception as e:
        logger.error(f"Error in db_rows_affected_log: {e}")

@track_time("DB: Verify Chatbot Access")
async def verify_chatbot_access(chatbot_id: str, email_id: str) -> bool:
    """
    Verify chatbot access using SQLModel instead of raw SQL.
    A user has access if they are the owner (in `chatbot_details`) or
    their email appears in `chatbot_invitations`.
    """
    try:
        possible_user_id = email_id.split('@')[0] if '@' in email_id else email_id
        async for session in get_async_session():
            owner_res = await session.execute(
                select(ChatbotDetails).where(
                    ChatbotDetails.chatbot_id == chatbot_id,
                    ChatbotDetails.user_id == possible_user_id,
                    ChatbotDetails.deleted != True
                ).limit(1)
            )
            if owner_res.scalars().first():
                return True

            inv_res = await session.execute(
                select(ChatbotInvitations).where(
                    ChatbotInvitations.chatbot_id == chatbot_id,
                    ChatbotInvitations.invited_user_email == email_id
                ).limit(1)
            )
            return inv_res.scalars().first() is not None
    except Exception as e:
        logger.error(f"Error in verify_chatbot_access: {str(e)}")
        return False