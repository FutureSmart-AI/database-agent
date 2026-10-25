## For the X-API Key Authorization of all API Endpoints
from fastapi.security import APIKeyHeader, APIKeyQuery
from fastapi import Depends, HTTPException, Header, status
from starlette.status import HTTP_401_UNAUTHORIZED
from fastapi import Security, HTTPException
import os
# from dotenv import load_dotenv
# load_dotenv()
# Rely on main.py or central config loader

from session.utils.auth import get_auth_details
from typing import Optional
from fastapi import Request

API_KEY_NAME = os.getenv("FASTAPI_SECRET_KEY")

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

async def get_api_key(
    api_key: str = Security(api_key_header)
):
    # Defensive: handle multiple headers
    if api_key:
        for key in api_key.split(","):
            if key.strip() == API_KEY_NAME:
                return True
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid API Key"
    )

async def get_api_key_or_session(
    request: Request,
    api_key: Optional[str] = Security(api_key_header),
):
    """
    Combined dependency that checks for either a valid session or a master API key.
    Prioritizes session authentication for browser users.
    """
    # 1. Check for session (Cognito)
    session_data = await get_auth_details(request, include_all_claims=True)
    if session_data:
        return {
            "auth_type": "session",
            "session_data": session_data,
            "user_id": session_data.get("email") or session_data.get("user_id")
        }

    # 2. Fallback to master API key
    if api_key:
        for key in api_key.split(","):
            if key.strip() == API_KEY_NAME:
                return {
                    "auth_type": "master_api_key",
                    "api_key": key.strip(),
                    "user_id": None
                }

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated: valid session or API key required"
    )