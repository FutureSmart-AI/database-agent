from datetime import datetime, timedelta
import pytz

from knowledge.services.sqlmodel_session import async_session
from models.sql_models import Users
from knowledge.services.logger import logger
from sqlmodel import select

async def extract_user_from_email(session_data):
    """
    Return the `user_id` from the provided session data fetched from auth service.
    Falls back to `all_claims.sub` if `user_id` is missing.
    """

    
    user_id = await get_user_id_from_email(session_data.get("email"))
    if user_id:
        return user_id
    else:
        if not session_data:
            return None
        user_id = session_data.get("user_id")
        if user_id:
            return user_id
        claims = session_data.get("all_claims", {}) or {}
        return claims.get("sub")

async def get_user_id_from_email(email):
    """Retrieve user ID from the database based on the email."""
    try:
        async with async_session() as session:
            statement = select(Users.user_id).where(Users.email_id == email)
            result = await session.execute(statement)
            user_id = result.scalar_one_or_none()

        if user_id:
            logger.info(f"Retrieved user ID for email: {email}")
            return user_id
        else:
            logger.info(f"No user ID found for email: {email}")
            return None
    except Exception as e:
        logger.error(f"Database error occurred during get_user_id_from_email: {str(e)}")
        return None