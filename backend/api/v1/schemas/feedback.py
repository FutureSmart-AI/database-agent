"""
Pydantic schemas for Feedback endpoints
"""
from pydantic import BaseModel, Field, model_validator
from typing import Optional


class FeedbackRequest(BaseModel):
    """Request model for feedback"""
    user_id: Optional[str] = Field(None, description="User ID (optional)")
    session_id: str = Field(..., description="Session ID")
    chat_id: str = Field(..., description="Chat message ID")
    user_query: str = Field(..., description="Original user query")
    generated_query: str = Field(..., description="Generated SQL query")
    label: str = Field(..., description="Feedback label: 'correct' or 'incorrect'")
    corrected_query: Optional[str] = Field(None, description="Corrected SQL query (optional, for incorrect feedback)")

    @model_validator(mode='before')
    @classmethod
    def strip_user_id_from_payload(cls, values):
        """Strip user_id from the payload to prevent spoofing"""
        if isinstance(values, dict):
            values.pop("user_id", None)
        return values

