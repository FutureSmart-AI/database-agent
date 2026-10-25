"""
Pydantic schemas for Column Descriptions endpoints
"""
from pydantic import BaseModel, Field, model_validator
from typing import Optional, List


class ColumnInfo(BaseModel):
    """Column information model"""
    column_name: str = Field(..., description="Name of the column")
    data_type: str = Field(..., description="Data type of the column")
    description: str = Field("", description="Description of the column")
    is_nullable: bool = Field(False, description="Whether the column is nullable")
    is_primary_key: bool = Field(False, description="Whether the column is a primary key")


class ColumnDescriptionUpdate(BaseModel):
    """Request model for updating column description"""
    column_name: str = Field(..., description="Name of the column")
    description: str = Field(..., description="Description of the column")


class BulkColumnDescriptionsRequest(BaseModel):
    """Request model for bulk column description updates"""
    user_id: Optional[str] = Field(None, description="User ID (optional if using auth token)")
    columns: List[ColumnDescriptionUpdate] = Field(..., description="List of column descriptions")

    @model_validator(mode='before')
    @classmethod
    def strip_user_id_from_payload(cls, values):
        """Strip user_id from the payload to prevent spoofing"""
        if isinstance(values, dict):
            values.pop("user_id", None)
        return values


class SingleColumnDescriptionRequest(BaseModel):
    """Request model for single column description update"""
    user_id: Optional[str] = Field(None, description="User ID (optional if using auth token)")
    description: str = Field(..., description="Description of the column")

    @model_validator(mode='before')
    @classmethod
    def strip_user_id_from_payload(cls, values):
        """Strip user_id from the payload to prevent spoofing"""
        if isinstance(values, dict):
            values.pop("user_id", None)
        return values

