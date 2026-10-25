from datetime import datetime, timedelta
import pytz

from models.sql_models import Users
from session.services.sqlmodel_session import async_session
from sqlmodel import select
from session.services.logger import logger

def calculate_ist_datetime(last_accessed_dt, hour=24):
    # Define the IST timezone
    ist = pytz.timezone("Asia/Kolkata")

    # Localize the last_accessed datetime to the IST timezone
    last_accessed_ist = last_accessed_dt.astimezone(ist)

    # Add 24 hours to the last_accessed datetime
    new_datetime_ist = last_accessed_ist + timedelta(hours=hour)

    # Separate the date and time parts
    new_date_ist = new_datetime_ist.date()
    new_time_ist = new_datetime_ist.time()

    return new_date_ist, new_time_ist


def get_time_remaining(last_accessed):
    """
    Calculate time remaining in HH:MM:SS format until the 24-hour period from last_accessed is complete.
    Returns time remaining as string in format 'HH:MM:SS'.
    """
    # Calculate the time when the 24-hour period will complete
    end_of_24_hours = last_accessed + timedelta(days=1)

    # Calculate the remaining time to reach the 24-hour completion
    time_remaining = end_of_24_hours - datetime.utcnow()  # We compare it with the current UTC time

    # Ensure time remaining is not negative (if it somehow exceeds the 24-hour period)
    if time_remaining.total_seconds() < 0:
        time_remaining = timedelta(0)  # Set to 0 if it's negative (edge case)

    # Convert remaining time to hours, minutes, seconds
    hours = int(time_remaining.seconds // 3600)
    minutes = int((time_remaining.seconds % 3600) // 60)
    seconds = int(time_remaining.seconds % 60)

    # Format the time as HH:MM:SS
    time_remaining_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    return time_remaining_str

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