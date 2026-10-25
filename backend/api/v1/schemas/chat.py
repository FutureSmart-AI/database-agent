"""
Pydantic schemas for Chat endpoints
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


# Each of these may be omitted, in which case the agent's saved setting applies (see
# api/v1/utils/chat_helper.py::apply_agent_answer_settings). Sending a value still wins, so
# callers that always send explicit flags are unaffected.
_OMITTABLE = " Omit to use the agent's saved setting."


class ChatRequest(BaseModel):
    """Request model for chat"""
    # Honored ONLY for trusted master-key callers (e.g. the chat service declaring the
    # end user it calls on behalf of). Session (browser) users are always identified from
    # their token and this field is ignored for them — see chat_with_agent. Not spoofable.
    user_id: Optional[str] = Field(None, description="End-user ID; honored only for master-key (server-to-server) callers")
    query: str = Field(..., description="Natural language query")
    session_id: Optional[str] = Field(None, description="Session ID (creates new if not provided)")
    debug_info: Optional[bool] = Field(None, description="Include debug information in response." + _OMITTABLE)
    chart_output: Optional[bool] = Field(None, description="Include chart output in response." + _OMITTABLE)
    allowed_charts: Optional[List[str]] = Field(None, description="List of allowed chart types." + _OMITTABLE)
    follow_up: Optional[bool] = Field(
        None,
        description="If true, also generate exactly two short follow-up questions for this turn." + _OMITTABLE,
    )


class SessionMessageRequest(BaseModel):
    """Request model for sending message to existing session (session_id comes from URL path)"""
    # See ChatRequest.user_id — honored only for trusted master-key callers.
    user_id: Optional[str] = Field(None, description="End-user ID; honored only for master-key (server-to-server) callers")
    query: str = Field(..., description="Natural language query")
    debug_info: Optional[bool] = Field(None, description="Include debug information in response." + _OMITTABLE)
    chart_output: Optional[bool] = Field(None, description="Include chart output in response." + _OMITTABLE)
    allowed_charts: Optional[List[str]] = Field(None, description="List of allowed chart types." + _OMITTABLE)
    follow_up: Optional[bool] = Field(
        None,
        description="If true, also generate exactly two short follow-up questions for this turn." + _OMITTABLE,
    )


class MessageHistoryResponse(BaseModel):
    """Response model for message history"""
    session_id: str
    messages: List[Dict[str, Any]]

