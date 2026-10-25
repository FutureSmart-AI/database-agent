"""Single-operator session login for an explicitly configured standalone install."""
import hmac
import os

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/v1/local-auth", include_in_schema=False)


def enabled():
    if os.getenv("MODE", "").lower() != "standalone":
        raise HTTPException(404)


def identity(request):
    if os.getenv("MODE", "").lower() != "standalone":
        return None
    email = os.getenv("STANDALONE_OWNER_EMAIL", "").strip().lower()
    if email and request.session.get("standalone_owner") == email:
        return {"email": email, "name": "Local operator", "user_id": email}
    return None


class Login(BaseModel):
    password: str


@router.post("/login")
async def login(body: Login, request: Request):
    enabled()
    # JSON-only login plus an exact origin boundary for browser POSTs.
    origin = request.headers.get("origin")
    expected = os.getenv("STANDALONE_ORIGIN", "http://localhost:3001")
    if origin and origin.rstrip("/") != expected.rstrip("/"):
        raise HTTPException(403, "Unrecognized login origin")
    password = os.getenv("STANDALONE_LOGIN_PASSWORD", "")
    email = os.getenv("STANDALONE_OWNER_EMAIL", "").strip().lower()
    if not password or not email:
        raise HTTPException(503, "Standalone login is not configured")
    if not hmac.compare_digest(body.password.encode(), password.encode()):
        raise HTTPException(401, "Invalid password")
    request.session.clear()
    request.session["standalone_owner"] = email
    return identity(request)


@router.get("/user/me")
async def profile(request: Request):
    enabled()
    result = identity(request)
    if not result:
        raise HTTPException(401, "Not authenticated")
    return result


@router.post("/logout")
async def logout(request: Request):
    enabled()
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") != os.getenv("STANDALONE_ORIGIN", "http://localhost:3001").rstrip("/"):
        raise HTTPException(403, "Unrecognized logout origin")
    request.session.clear()
    return {"ok": True}
