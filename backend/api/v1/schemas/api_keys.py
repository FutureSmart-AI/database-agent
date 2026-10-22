"""
Pydantic schemas for per-agent API key endpoints
"""
from pydantic import BaseModel, Field
from typing import Optional, List


class GenerateApiKeyRequest(BaseModel):
    """Request model for issuing an agent API key"""
    user_id: Optional[str] = Field(
        None,
        description="Owner of the key. Required for master-key callers; ignored for session callers, where the signed-in user is used.",
    )


class ApiKeyResponse(BaseModel):
    """Response model for issuing an agent API key"""
    api_key: str = Field(..., description="The API key. Send it as the X-API-Key header.")
    agent_id: str = Field(..., description="Agent this key is scoped to")
    user_id: Optional[str] = Field(None, description="Owner of the key")
    created_at: Optional[str] = Field(None, description="ISO timestamp of creation")
    message: Optional[str] = Field(None, description="Human-readable result of the call")


class ApiKeyInfo(BaseModel):
    """One API key as returned by the listing endpoint"""
    api_key: str
    agent_id: Optional[str] = None
    user_id: Optional[str] = None
    is_active: bool
    created_at: Optional[str] = None
    revoked_at: Optional[str] = None


class ApiKeyListResponse(BaseModel):
    """Response model for listing an agent's API keys"""
    api_keys: List[ApiKeyInfo]
