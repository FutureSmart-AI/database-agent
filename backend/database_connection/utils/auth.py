from typing import Optional
from urllib.parse import urlparse
from fastapi import Query, Request
import httpx
import logging

from database_connection.services.sqlmodel_session import async_session
from sqlmodel import select
from models.sql_models import Users
logger = logging.getLogger(__name__)


def _extract_host_from_request(request: Optional["Request"]) -> str:
    try:
        if not request:
            return ""
        origin = request.headers.get("origin") or ""
        referer = request.headers.get("referer") or ""
        xfh = request.headers.get("x-forwarded-host") or ""
        host_hdr = request.headers.get("host") or ""

        if origin:
            return (urlparse(origin).hostname or "").lower()
        if referer:
            return (urlparse(referer).hostname or "").lower()
        if xfh:
            return xfh.split(":")[0].lower()
        if host_hdr:
            return host_hdr.split(":")[0].lower()
        return ""
    except Exception:
        return ""


def resolve_access_cookie_key_from_host(host: Optional[str]) -> str:
    try:
        h = (host or "").strip().lower()
    except Exception:
        h = ""

    parts = [p for p in h.split(".") if p]
    first_label = parts[0] if parts else None
    if first_label:
        return f"{first_label}_access_token"
    return "access_token"


def resolve_access_cookie_key_from_request(request: Optional["Request"]) -> str:
    host = _extract_host_from_request(request)
    return resolve_access_cookie_key_from_host(host)


async def get_auth_details(request: Request, include_all_claims: Optional[bool] = Query(default=False)):
    # 1. Try Authorization header
    auth_header = request.headers.get("authorization") or ""
    access_token = None
    if auth_header.lower().startswith("bearer "):
        access_token = auth_header[7:].strip()
        logger.info("Access token found in Authorization header")

    # 2. Try cookies if not in header
    if not access_token:
        cookie_key = resolve_access_cookie_key_from_request(request)
        access_token = (
            request.cookies.get(cookie_key)
            or request.cookies.get("agent_access_token")
            or request.cookies.get("access_token")
        )
        if access_token:
            logger.info("Access token found in cookies (key=%s)", cookie_key)

    if not access_token:
        logger.info("No Access Token provided in headers or cookies")
        return None

    url = f"https://auth.futuresmart.ai/user/me?include_all_claims={include_all_claims}&access_token={access_token}"

    headers = {"accept": "application/json"}

    async with httpx.AsyncClient() as client: 
        response = await client.get(url, headers=headers)

    if response.status_code == 200:
        return response.json()
    else:
        logger.error(f"Invalid Access Token: {response.status_code} - {response.text}")
        return None

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
