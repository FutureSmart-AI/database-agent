from typing import Optional
from urllib.parse import urlparse
from fastapi import Query, Request
import httpx
import logging

from knowledge.services.sqlmodel_session import async_session
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
    """Map a request host to the access token cookie key.

    Examples:
    - agent.futuresmart.ai -> agent_access_token
    - staging.agent.futuresmart.ai -> staging_access_token
    - nl2sql.futuresmart.ai -> nl2sql_access_token

    Always use the left-most label (e.g., 'aidemos' for aidemos.com, 'agent' for agent.futuresmart.ai).
    For unknown/empty hosts, fall back to "access_token".
    """
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

    # Check response status and content
    if response.status_code == 200:
        return response.json()
    else:
        logger.error(f"Invalid Access Token: {response.status_code} - {response.text}")
        return None


