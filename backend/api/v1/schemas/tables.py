"""
Pydantic schemas for Table Descriptions endpoints
"""
from pydantic import BaseModel, Field, model_validator
from typing import Optional, List


class TableDescriptionItem(BaseModel):
    """Single table description"""
    table_name: str = Field(..., description="Table name")
    description: str = Field(..., description="Table description")


class BulkTableDescriptionsRequest(BaseModel):
    """Request model for bulk table descriptions"""
    user_id: Optional[str] = Field(None, description="User ID (optional if using auth token)")
    tables: List[TableDescriptionItem] = Field(..., description="List of table descriptions")

    @model_validator(mode='before')
    @classmethod
    def strip_user_id_from_payload(cls, values):
        """Strip user_id from the payload to prevent spoofing"""
        if isinstance(values, dict):
            values.pop("user_id", None)
        return values


class TableVisibilityItem(BaseModel):
    """Single table visibility setting"""
    table_name: str = Field(..., description="Table name")
    is_included: bool = Field(..., description="Whether table is included")


class BulkTableVisibilityRequest(BaseModel):
    """Request model for bulk table visibility updates"""
    tables: List[TableVisibilityItem] = Field(..., description="List of table visibility settings")


class SingleTableVisibilityRequest(BaseModel):
    """Request model for single table visibility update"""
    is_included: bool = Field(..., description="Whether table is included")


class SingleTableUpdateRequest(BaseModel):
    """Request model for updating a single table description"""
    description: str = Field(..., description="Table description")
    is_included: Optional[bool] = Field(None, description="Whether table is included (optional)")


class DeleteTablesRequest(BaseModel):
    """Clear table descriptions by name, or all of them. (Tables are not deleted — only their
    description text is cleared.)"""
    table_names: Optional[List[str]] = Field(None, description="Table names to clear", examples=[["t1", "t2"]])
    delete_all: bool = Field(False, description="Clear ALL table descriptions for this database")

    @model_validator(mode='before')
    @classmethod
    def accept_tables_alias(cls, values):
        """Accept the legacy 'tables' key as an alias for 'table_names'."""
        if isinstance(values, dict) and not values.get("table_names") and values.get("tables"):
            values["table_names"] = values["tables"]
        return values


class HighCardinalityColumnItem(BaseModel):
    """Single high cardinality column"""
    table_name: str = Field(..., description="Table name")
    column_name: str = Field(..., description="Column name")


class HighCardinalityColumnsRequest(BaseModel):
    """Request model for high cardinality columns"""
    columns: List[HighCardinalityColumnItem] = Field(..., description="List of high cardinality columns")

