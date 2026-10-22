"""
Pydantic schemas for Few-Shot Examples endpoints
"""
from pydantic import BaseModel, Field
from typing import List, Optional


class FewShotExampleItem(BaseModel):
    """Single few-shot example"""
    natural_query: str = Field(..., description="Natural language query")
    sql_query: str = Field(..., description="Corresponding SQL query")


class BulkFewShotExamplesRequest(BaseModel):
    """Request model for bulk few-shot examples"""
    examples: List[FewShotExampleItem] = Field(..., description="List of few-shot examples")


class BulkDeleteFewShotRequest(BaseModel):
    """Delete multiple few-shot examples by their natural-language query, or all of them."""
    nl_queries: Optional[List[str]] = Field(
        None, description="Natural-language queries of the examples to delete",
        examples=[["Show top customers", "count orders"]])
    delete_all: bool = Field(False, description="Delete ALL few-shot examples for this database")

