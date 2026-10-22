# Simplified pydantic models for agent
from pydantic import BaseModel, Field, field_validator
from typing import Dict, Any, List, Optional
import logging

logger = logging.getLogger(__name__)

class PostProcessorOutput(BaseModel):
    graph_suggestion: str
    graph_data: List[Dict[str, Any]]

    @field_validator('graph_data', mode='before')
    def ensure_required_key_last(cls, value):
        required_keys = {'count', 'frequency', 'value'}
        processed_list = []

        for index, item in enumerate(value):
            if not isinstance(item, dict):
                logger.error(f"Item at index {index} is not a dictionary")
                break
            intersection = required_keys & item.keys()
            if not intersection:
                logger.error(f"Dictionary at index {index} does not contain any of the required keys: {required_keys}")
                break
            # Select one of the required keys
            selected_key = intersection.pop()
            # Create a new dictionary ensuring the selected key is last
            reordered_dict = {k: v for k, v in item.items() if k != selected_key}  # Retain all except selected key
            reordered_dict[selected_key] = item[selected_key]  # Append selected key at the end
            processed_list.append(reordered_dict)

        return processed_list
    
class Chat(BaseModel):
    """
    Chat model - kept for backward compatibility with any remaining internal utilities.
    New RESTful API uses ChatRequest from api.v1.schemas.chat instead.
    """
    user_id: Optional[str] = None
    agent_id: str  # Agent ID (required)
    query: str
    session_id: Optional[str] = None
    debug_info: Optional[bool] = Field(default=False)
    graph_output: Optional[bool] = Field(default=False)
    allowed_graphs: Optional[List[str]] = None