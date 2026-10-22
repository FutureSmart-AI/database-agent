"""
Pydantic schemas for Session endpoints
"""
from pydantic import BaseModel, Field, model_validator
from typing import Optional, List
from datetime import datetime


class SessionResponse(BaseModel):
    """Response model for a single session"""
    session_id: str
    created_time: Optional[datetime] = None
    display_message: Optional[str] = None
    session_title: Optional[str] = None
    user_id: Optional[str] = None


class SessionListResponse(BaseModel):
    """Response model for list of sessions"""
    sessions: List[SessionResponse]
    meta: Optional[dict] = None


class SessionDetailResponse(BaseModel):
    """Response model for session details with conversation data"""
    session_id: str
    session_title: Optional[str] = None
    created_time: Optional[datetime] = None
    conversation_data: Optional[List[dict]] = None


class UpdateSessionRequest(BaseModel):
    """Request model for updating session (PATCH)"""
    session_title: Optional[str] = Field(None, description="New session title")
    user_id: Optional[str] = Field(None, description="User ID (optional)")

    @model_validator(mode='before')
    @classmethod
    def strip_user_id_from_payload(cls, values):
        """Strip user_id from the payload to prevent spoofing"""
        if isinstance(values, dict):
            values.pop("user_id", None)
        return values

