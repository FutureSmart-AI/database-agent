"""
Pydantic schemas for NL2SQL Service validation endpoints
"""
from pydantic import BaseModel, Field
from typing import Optional, List


class ValidateServiceResponse(BaseModel):
    """Response model for service validation"""
    valid: bool = Field(..., description="Whether the service is valid")

class ListServicesResponse(BaseModel):
    """Response model for listing services"""
    owner_id: Optional[str] = Field(None, description="Owner/user identifier (if filtered)")
    service_ids: List[str] = Field(..., description="List of service IDs (agent_ids)")
    count: int = Field(..., description="Number of services")



