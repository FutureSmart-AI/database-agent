"""
Pydantic schemas for Agent endpoints
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


# Applied when the caller does not say otherwise. A new agent is far more often
# a SaaS one than not, and an agent with no business rules answers revenue and
# churn questions confidently wrong - so the useful default is the template
# rather than nothing. Pass template_id=null explicitly for a bare agent.
DEFAULT_TEMPLATE_ID = "saas_founder"


class CreateAgentRequest(BaseModel):
    """Request model for creating a new agent

    owner_id is the email of the agent owner (optional).
    """
    owner_id: Optional[str] = Field(None, description="Owner email address (optional)")
    agent_name: str = Field(..., description="Name of the agent")
    system_prompt: Optional[str] = Field(None, description="System prompt for the agent")
    greet_message: Optional[str] = Field(None, description="Greeting message")
    provider: Optional[str] = Field("openai", description="LLM provider")
    model: Optional[str] = Field("gpt-5.4-mini", description="Model name")
    temperature: Optional[float] = Field(0.0, ge=0.0, le=2.0, description="Temperature for LLM")
    show_sql_query: Optional[bool] = Field(True, description="If true, the chat response will include the generated SQL query")
    show_db_result: Optional[bool] = Field(True, description="If true, the chat response will include the raw DB result rows")
    template_id: Optional[str] = Field(
        DEFAULT_TEMPLATE_ID,
        description=(
            "Use-case template applied at creation. Defaults to the SaaS founder "
            "template, which is currently the only one. Pass null for a bare agent "
            "with no business rules; an unknown id is ignored and the agent is "
            "still created."
        ),
    )


class UpdateAgentRequest(BaseModel):
    """Request model for updating an agent (full update)"""
    agent_name: Optional[str] = Field(None, description="Name of the agent")
    system_prompt: Optional[str] = Field(None, description="System prompt for the agent")
    greet_message: Optional[str] = Field(None, description="Greeting message")
    provider: Optional[str] = Field(None, description="LLM provider")
    model: Optional[str] = Field(None, description="Model name")
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0, description="Temperature for LLM")
    show_sql_query: Optional[bool] = Field(None, description="If true, the chat response will include the generated SQL query")
    show_db_result: Optional[bool] = Field(None, description="If true, the chat response will include the raw DB result rows")


class PatchAgentRequest(BaseModel):
    """Request model for partially updating an agent"""
    agent_name: Optional[str] = Field(None, description="Name of the agent")
    system_prompt: Optional[str] = Field(None, description="System prompt for the agent")
    greet_message: Optional[str] = Field(None, description="Greeting message")
    provider: Optional[str] = Field(None, description="LLM provider")
    model: Optional[str] = Field(None, description="Model name")
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0, description="Temperature for LLM")
    show_sql_query: Optional[bool] = Field(None, description="If true, the chat response will include the generated SQL query")
    show_db_result: Optional[bool] = Field(None, description="If true, the chat response will include the raw DB result rows")


class AgentResponse(BaseModel):
    """Response model for agent data

    owner_id: The email of the user who owns/created this agent
    """
    agent_id: str
    owner_id: str = Field(..., description="The email address of the agent owner")
    agent_name: str
    system_prompt: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = None
    greet_message: Optional[str] = None
    show_sql_query: Optional[bool] = None
    show_db_result: Optional[bool] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class AgentListResponse(BaseModel):
    """Response model for list of agents"""
    agents: List[AgentResponse]
    total: int


class AgentParametersResponse(BaseModel):
    """Response model for agent parameters"""
    agent_id: str
    agent_name: str
    system_prompt: Optional[str] = None
    greet_message: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = None


class UpdateAgentParametersRequest(BaseModel):
    """Request model for updating agent parameters"""
    owner_id: Optional[str] = Field(None, description="Owner ID (optional if using auth token)")
    agent_name: Optional[str] = Field(None, description="Name of the agent")
    system_prompt: Optional[str] = Field(None, description="System prompt for the agent")
    greet_message: Optional[str] = Field(None, description="Greeting message")
    provider: Optional[str] = Field(None, description="LLM provider (e.g., openai, anthropic)")
    model: Optional[str] = Field(None, description="Model name (e.g., gpt-4.1-mini)")
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0, description="Temperature for LLM")
