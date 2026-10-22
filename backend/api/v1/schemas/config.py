"""
Pydantic schemas for Agent Configuration endpoints
"""
from pydantic import BaseModel, Field, model_validator
from typing import Optional, List


class NodeConfig(BaseModel):
    """Node configuration model"""
    node_name: str = Field(..., description="Node name (must be one of: refine, select_and_fewshots, sql_gen, sql_exec, final_answer_node, graph_json_node)")
    provider: str = Field(..., description="LLM provider (e.g., openai, anthropic, groq)")
    model: str = Field(..., description="Model name (e.g., gpt-4o, gpt-4o-mini, claude-3-5-sonnet)")
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0, description="Temperature for LLM")
    # max_tokens: Optional[int] = Field(2000, gt=0, description="Maximum tokens")
    # is_default: bool = Field(False, description="Whether this is the default node")
    prompt: Optional[str] = Field(None, description="Custom prompt for this node")


class NodeConfigsRequest(BaseModel):
    """Request model for upserting node configurations
    
    Note: owner_id is used as a fallback for user_id if auth token is not provided.
    This is for backward compatibility. The authenticated user must own the agent.
    """
    owner_id: Optional[str] = Field(None, description="User ID (optional if using auth token)")
    configs: List[NodeConfig] = Field(..., description="List of node configurations to upsert")

    @model_validator(mode='before')
    @classmethod
    def strip_user_id_from_payload(cls, values):
        """Strip owner_id from the payload to prevent spoofing"""
        if isinstance(values, dict):
            values.pop("owner_id", None)
        return values

class AgentParamsRequest(BaseModel):
    """Request model for updating agent parameters"""
    owner_id: Optional[str] = Field(None, description="Owner ID (optional if using auth token)")
    agent_name: Optional[str] = Field(None, description="Name of the agent")
    system_prompt: Optional[str] = Field(None, description="System prompt for the agent")
    service_description: Optional[str] = Field(None, description="Service description for the agent")
    greet_message: Optional[str] = Field(None, description="Greeting message")
    debug_info: Optional[bool] = Field(None, description="Enable debug information")
    show_sql_query: Optional[bool] = Field(None, description="If true, the chat response includes the generated SQL query")
    show_db_result: Optional[bool] = Field(None, description="If true, the chat response includes the raw DB result rows")
    graph_output: Optional[bool] = Field(None, description="Enable graph output")
    allowed_graphs: Optional[List[str]] = Field(None, description="List of allowed graph types (e.g., bar, line, pie)")
    follow_up: Optional[bool] = Field(None, description="Suggest follow-up questions after each answer")
    voice_input_enabled: Optional[bool] = Field(None, description="Offer speech input in the ask box")
    voice_output_enabled: Optional[bool] = Field(None, description="Offer read-aloud on each answer")
    suggested_questions: Optional[List[str]] = Field(None, description="Starter questions shown before the first message")
    max_query_execution_time: Optional[int] = Field(None, description="Maximum query execution time in seconds")
    enable_query_caching: Optional[bool] = Field(None, description="Enable query caching")
    is_public: Optional[bool] = Field(None, description="Allow the embedded widget to be used without signing in")
    allowed_domains: Optional[List[str]] = Field(None, description="Domains the widget may be embedded on (e.g. ['example.com', '*.example.com']). Empty means any domain")
    fullscreen_is_public: Optional[bool] = Field(None, description="Allow the full-screen share link to be used without signing in")
    fullscreen_allowed_domains: Optional[List[str]] = Field(None, description="Domains the full-screen link may be opened from. Empty means any domain")

    @model_validator(mode='before')
    @classmethod
    def strip_user_id_from_payload(cls, values):
        """Strip owner_id from the payload to prevent spoofing"""
        if isinstance(values, dict):
            values.pop("owner_id", None)
        return values
