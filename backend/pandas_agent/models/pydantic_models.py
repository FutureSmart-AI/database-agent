from pydantic import BaseModel, Field
from typing import List, Optional


# --- Pandas Agent Models ---
class PandasOperation(BaseModel):
    """Single pandas operation to execute."""
    code: str = Field(..., description="Pandas operation code snippet.")
    reason: Optional[str] = Field(None, description="Reason for this operation.")

class DataTransformationPlan(BaseModel):
    """Plan for transforming CSV data using pandas."""
    operations: List[PandasOperation] = Field(..., description="List of pandas operations to execute in sequence.")
    final_output: str = Field("result_df", description="Name of the final output DataFrame variable.")
    reasoning: str = Field(..., description="Overall reasoning for the transformation plan.")    
