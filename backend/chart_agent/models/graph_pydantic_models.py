from enum import Enum
from pydantic import BaseModel,Field, field_validator
from typing import Optional, Union, List, Dict, Any
from .chart_pydantic_models import (
    BarColumnChartData, PieChartData, LineChartData, StackedBarChartData, BubbleChartData, GeoChartData, ScatterChartData
)

class ChartType(str, Enum):
    BAR_CHART = "Bar Chart"
    PIE_CHART = "Pie Chart"
    LINE_CHART = "Line Chart"
    STACKED_BAR_CHART = "Stacked Bar Chart"
    BUBBLE_CHART = "Bubble Chart"
    GEO_CHART = "Geo Chart"
    SCATTER_CHART = "Scatter Chart"
    COLUMN_CHART = "Column Chart"

class ChartTypeResponse(BaseModel):
    chart_type: ChartType

class GraphRequest(BaseModel):
    user_id: Optional[str] = Field(None, description="Unique identifier for the user.")
    question: str = Field(..., description="Natural language question.")
    raw_data: Union[str, List[Dict[str, Any]]] = Field(..., description="Raw data as JSON string or list of objects.")
    allowed_graphs: Optional[List[ChartType]] = Field(None, description="List of allowed chart types. If not provided, all chart types are allowed.")

    @field_validator('question')
    @classmethod
    def question_must_not_be_blank(cls, v: str) -> str:
        if v is None or v.strip() == "":
            raise ValueError("question is required and cannot be blank")
        return v

    @field_validator('raw_data')
    @classmethod
    def raw_data_must_not_be_empty(cls, v: Union[str, List[Dict[str, Any]]]):
        if v is None:
            raise ValueError("raw_data is required and cannot be null")
        if isinstance(v, str) and v.strip() == "":
            raise ValueError("raw_data is required and cannot be blank")
        if isinstance(v, list) and len(v) == 0:
            raise ValueError("raw_data is required and cannot be empty")
        return v

class GraphData(BaseModel):
    data: List[Dict[str, Any]]
    metadata: Dict[str, Any]

class DataFrameStructure(BaseModel):
    """Structured representation of a DataFrame with columns, data, shape, and dtypes."""
    columns: List[str] = Field(..., description="Column names of the DataFrame")
    data: List[Dict[str, Any]] = Field(..., description="Data rows as list of dictionaries")
    shape: List[int] = Field(..., description="Shape of the DataFrame as [rows, columns]")
    dtypes: Dict[str, str] = Field(..., description="Data types of each column")

class GraphResponse(BaseModel):
    graph_suggestion: str = Field(..., description="Suggested chart type")
    graph_data: GraphData = Field(..., description="Graph data with data array and metadata")
    dataframe: Optional[DataFrameStructure] = Field(None, description="Structured representation of the processed DataFrame used for graph generation")
    token_metrics: Optional[Dict[str, Any]] = Field(None, description="Aggregated token usage metrics for LLM calls")

# --- Master Dictionary for Model Lookup ---
GRAPH_PYDANTIC_MODELS = {
    "Bar Chart": BarColumnChartData,
    "Pie Chart": PieChartData,
    "Line Chart": LineChartData,
    "Stacked Bar Chart": StackedBarChartData,
    "Bubble Chart": BubbleChartData,
    "Geo Chart": GeoChartData,
    "Scatter Chart": ScatterChartData,
    "Column Chart": BarColumnChartData,
}



# Graph agent Pydantic Models

class GraphQueryRequest(BaseModel):
    query: str
    allowed_graphs: Optional[List[ChartType]] = None  # e.g., ["bar", "pie"]


class GraphQueryResponse(BaseModel):
    graph_suggestion: str
    graph_data: dict
    dataframe: dict



# New response model for direct responses
class DirectResponse(BaseModel):
    """Response for non-graph queries (greetings, general questions)"""
    type: str = "direct_response"
    message: str
    reasoning: Optional[str] = None
    graph_generated: bool = False


class GraphGenerationResponse(BaseModel):
    """Response for successful graph generation"""
    type: str = "chart_response"
    chart_suggestion: str
    chart_data: GraphData
    dataframe: Optional[dict] = None
    chart_generated: bool = True
  
