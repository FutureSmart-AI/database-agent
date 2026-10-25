from agent.utils.model_profiles import operation_config, build_chat_model, configured_model_factory, ModelConfigurationError
"""
Graph Mapper Module (Schema-Only Approach)

This module generates graph field mappings using ONLY DataFrame schema information.
The LLM NEVER sees actual data values - only column names and data types.

WORKFLOW:
1. DataFrame transformed → Extract schema (columns, dtypes)
2. LLM receives: user_query, schema, chart_type
3. LLM outputs: Field mappings + metadata (colors, legends, etc.)
4. Python function uses mappings to generate complete graph data with actual values
"""

import pandas as pd
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
import os
try:
    from langchain_groq import ChatGroq
    ChatModel = ChatGroq
except Exception:
    from agent.utils.openai_chat_kwargs import product_chat_openai as ChatOpenAI
    ChatModel = ChatOpenAI

from agent.utils.openai_chat_kwargs import product_chat_openai as FallbackModel
ChatOpenAI = FallbackModel

try:
    from groq import RateLimitError as GroqRateLimitError, BadRequestError as GroqBadRequestError  # type: ignore
except Exception:  # pragma: no cover - groq SDK not installed
    GroqRateLimitError = Exception  # type: ignore[misc,assignment]
    GroqBadRequestError = Exception  # type: ignore[misc,assignment]

try:
    from openai import BadRequestError as OpenAIBadRequestError
except Exception:  # pragma: no cover - openai SDK not installed
    OpenAIBadRequestError = Exception  # type: ignore[misc,assignment]

import json
from logger import logger
from chart_agent.utils.model_config_loader import load_model_config
from agent.utils.openai_chat_kwargs import structured_tool_chat_kwargs


# ============================================================================
# DATAFRAME SCHEMA EXTRACTION
# ============================================================================

def extract_dataframe_schema(df: pd.DataFrame) -> Dict[str, Any]:
    """Extract only schema information from DataFrame (no actual data values)"""
    schema = {
        "shape": {
            "rows": int(df.shape[0]),
            "columns": int(df.shape[1])
        },
        "columns": {}
    }

    for col in df.columns:
        dtype = str(df[col].dtype)

        # Basic column info
        col_info = {
            "dtype": dtype,
            "nullable": bool(df[col].isna().any())
        }

        # Add type-specific metadata (not values!)
        if pd.api.types.is_numeric_dtype(df[col]):
            col_info["type_category"] = "numeric"
            col_info["has_decimals"] = dtype in ['float64', 'float32']
        elif pd.api.types.is_datetime64_any_dtype(df[col]):
            col_info["type_category"] = "datetime"
        elif isinstance(df[col].dtype, pd.CategoricalDtype):
            col_info["type_category"] = "categorical"
            col_info["num_categories"] = len(df[col].cat.categories)
        else:
            col_info["type_category"] = "string"

        schema["columns"][col] = col_info

    return schema


# ============================================================================
# FIELD MAPPING MODELS (LLM Output)
# ============================================================================

class FieldMapping(BaseModel):
    """Maps a DataFrame column to a graph field"""
    graph_field: str = Field(description="The target field name in the graph model (e.g., 'category', 'value', 'x', 'y')")
    dataframe_column: str = Field(description="The source column name in the DataFrame")
    description: str = Field(description="Why this mapping makes sense")


class MetadataConfig(BaseModel):
    """Configuration for graph metadata (colors, legends, axes, etc.)"""
    title: str = Field(description="Chart title based on user query")
    x_axis_label: Optional[str] = Field(None, description="Label for x-axis")
    y_axis_label: Optional[str] = Field(None, description="Label for y-axis")
    show_legend: bool = Field(default=True, description="Whether to show legend")
    legend_position: Optional[str] = Field("right", description="Legend position: top, right, bottom, left")
    # Optional legend title and items. If not provided, backend will derive sensible defaults
    # (e.g., for stacked charts, items derived from segment categories or value columns).
    legend_title: Optional[str] = Field(
        None,
        description="Optional heading for the legend (e.g., 'Skill', 'Language')"
    )
    legend_items: Optional[List[str]] = Field(
        None,
        description="Optional explicit list of legend item labels. If omitted, chart_agent will infer them where possible."
    )
    color_scheme: Optional[str] = Field("default", description="Color scheme: default, warm, cool, monochrome")
    
    class Config:
        extra = "forbid"  # Don't allow additional fields


class GraphMappingSpec(BaseModel):
    """Complete specification for mapping DataFrame to graph"""
    chart_type: str = Field(description="The chart type being generated")
    field_mappings: List[FieldMapping] = Field(description="List of field mappings from DataFrame columns to graph fields")
    measure_columns: List[str] = Field(
        description=(
            "Every DataFrame column that holds a quantity the chart should plot as its own series "
            "(for example revenue or order_count). Exclude identifiers and keys such as id, "
            "customer_id or codes even when they are numeric, and exclude columns used only as labels."
        )
    )
    label_columns: List[str] = Field(
        description=(
            "The column or columns that together name each plotted item, in display order "
            "(for example ['first_name', 'last_name'] for a person). Use one column when one "
            "column already names the item. Do not include identifiers when a name column exists."
        )
    )
    metadata_config: MetadataConfig = Field(description="Configuration for graph metadata")
    reasoning: str = Field(description="Explanation of why these mappings were chosen")


# ============================================================================
# CHART TYPE REQUIREMENTS
# ============================================================================

CHART_REQUIREMENTS = {
    "Bar Chart": [
        {"field": "category", "type": "string", "description": "Categories for bars"},
        {"field": "value", "type": "numeric", "description": "Values for bar heights"}
    ],
    "Column Chart": [
        {"field": "category", "type": "string", "description": "Categories for columns"},
        {"field": "value", "type": "numeric", "description": "Values for column heights"}
    ],
    "Pie Chart": [
        {"field": "label", "type": "string", "description": "Labels for pie slices"},
        {"field": "value", "type": "numeric", "description": "Values for slice sizes"}
    ],
    "Line Chart": [
        {"field": "x", "type": "string/numeric/datetime", "description": "X-axis values"},
        {"field": "y", "type": "numeric", "description": "Y-axis values"}
    ],
    "Stacked Bar Chart": [
        {"field": "index", "type": "string", "description": "Main categories (bar indices)"},
        {"field": "segment_category", "type": "string", "description": "Segment categories within each bar"},
        {"field": "segment_value", "type": "numeric", "description": "Values for each segment"}
    ],
    "Bubble Chart": [
        {"field": "x", "type": "numeric", "description": "X-axis position"},
        {"field": "y", "type": "numeric", "description": "Y-axis position"},
        {"field": "size", "type": "numeric", "description": "Bubble size"},
        {"field": "label", "type": "string", "description": "Bubble labels"}
    ],
    "Scatter Chart": [
        {"field": "x", "type": "numeric", "description": "X-axis values"},
        {"field": "y", "type": "numeric", "description": "Y-axis values"}
    ],
    "Geo Chart": [
        {"field": "country", "type": "string", "description": "3-letter ISO country code (e.g., USA, JPN, AUS)"},
        {"field": "value", "type": "numeric", "description": "Numeric value for the geographic heatmap"}
    ],
}


def get_chart_requirements(chart_type: str) -> str:
    """Get formatted requirements string for a chart type"""
    requirements = CHART_REQUIREMENTS.get(chart_type, [])
    return "\n".join([
        f"  - {req['field']}: {req['type']} - {req['description']}"
        for req in requirements
    ])


# ============================================================================
# SYSTEM PROMPT
# ============================================================================

def get_mapping_system_prompt(chart_type: str, additional_instruction: Optional[str] = None) -> str:
    """Generate system prompt for the graph mapping LLM"""
    
    requirements_str = get_chart_requirements(chart_type)
    
    prompt= f"""You are a data visualization expert that maps DataFrame columns to {chart_type} fields.

**Your Task:**
Given a DataFrame schema (column names and types only), map the columns to the required {chart_type} fields.

**Required Mappings for {chart_type.upper()}:**
{requirements_str}

**Rules:**
1. You will ONLY see column names and data types - NO actual data values
2. Map DataFrame columns to the required graph fields based on column names and types
3. Choose the most semantically appropriate columns for each field
4. Provide clear reasoning for your mappings
5. Generate appropriate metadata (title, axis labels, legend settings)
6. Select an appropriate color scheme: default, warm, cool, or monochrome
7. Classify the columns: list the quantities to plot in measure_columns and the columns
   that name each item in label_columns. Identifier and key columns (id, customer_id,
   codes) are neither, even when numeric. If an item's name spans several columns, list
   them all in label_columns and map the chart's label field to the first of them; the
   chart displays them joined.

**Output Format:**
Provide a complete GraphMappingSpec with:
- chart_type: The chart type
- field_mappings: List of FieldMapping objects
- measure_columns: the columns holding plotted quantities (never identifiers)
- label_columns: the columns that name each plotted item
- metadata_config: MetadataConfig with title, labels, and display settings.
  - When multiple series or segments exist (for example, several numeric columns being compared across a shared category, or a categorical column that defines groups/segments),
    you MUST:
      - set legend_title to a short description of what those series/segments represent (for example, "Status", "Product", "Skill", or "Region", depending on the schema and user query).
      - set legend_items to the human-readable labels for each series/segment, derived from the column names or category values in the schema (do NOT use generic names like "Series 1", "Series 2").
- reasoning: Explanation of your mapping choices

Be smart about column selection based on semantic meaning and data types."""
    prompt += "\n\nAdditional Instruction:\n"
    if additional_instruction:
        prompt += f"\n\n\n{additional_instruction}"
    return prompt

# ============================================================================
# GRAPH MAPPING FUNCTION
# ============================================================================

async def generate_graph_mapping(
    df_schema: Dict[str, Any],
    user_query: str,
    chart_type: str,
    owner_id: Optional[str] = None,
    model: str = None,
    provider: Optional[str] = None,
    temperature: float = 0,
    verbose: bool = True,
    custom_instruction: str = None,
    model_config: Optional[Dict[str, Any]] = None
) -> GraphMappingSpec:
    """
    Generate graph field mappings from DataFrame schema (no actual data).

    Args:
        df_schema: DataFrame schema (from extract_dataframe_schema)
        user_query: User's original query
        chart_type: Type of chart to generate
        owner_id: Owner ID for credential lookup
        model: LLM model to use
        temperature: LLM temperature
        verbose: Print progress
        custom_instruction: Optional custom instruction for mapping

    Returns:
        GraphMappingSpec with field mappings and metadata config
    """
    if verbose:
        print("=" * 80)
        print("🗺️  GRAPH MAPPING (Schema-Only)")
        print("=" * 80)
        print(f"📊 Chart Type: {chart_type}")
        print(f"📝 User Query: {user_query}")
        print(f"📁 DataFrame Schema:")
        print(f"   Columns: {list(df_schema['columns'].keys())}")
        print(f"   Shape: {df_schema['shape']}")
        print("=" * 80 + "\n")

    # Create system prompt (include any custom instruction)
    system_prompt = get_mapping_system_prompt(chart_type, additional_instruction=custom_instruction)

    # Create user message with schema
    user_message = f"""Map the DataFrame columns to {chart_type} fields.

**User Query:** {user_query}

**DataFrame Schema:**
```json
{json.dumps(df_schema, indent=2)}
```

Generate the field mappings and metadata configuration."""
    if custom_instruction:
        user_message += f"\n\nAdditional Instructions for chart_agent (mapper):\n{custom_instruction}"

    # Initialize LLM with structured output - use provider to select correct LLM class
    from agent.utils.owner_credential_utils import get_llm_api_key, get_provider_from_model
    
    override = {"provider": provider, "model": model} if model or provider else None
    conf = model_config or operation_config("chart_agent.mapping", override)
    provider_lower, model = conf["provider"], conf["model"]

    # Get API keys with logging - pass provider so correct key is loaded
    logger.info(f"🤖 [LLM_CALL] Graph Mapper | owner_id: {owner_id} | model: {model} | provider: {provider_lower}")
    api_key = await get_llm_api_key(owner_id, model, provider_lower)
    
    # Log which credential source is being used
    if api_key:
        logger.info(f"🚀 [LLM_CALL] Graph Mapper initialized | owner_id: {owner_id} | model: {model} | provider: {provider_lower}")
    else:
        logger.warning(f"⚠️ [LLM_CALL] Graph Mapper using default env credentials | owner_id: {owner_id} | model: {model} | provider: {provider_lower}")
    
    llm = build_chat_model(conf, api_key=api_key)
    method = {} if provider_lower in ("google", "anthropic") else {"method": "json_mode" if provider_lower == "deepseek" else "function_calling"}
    structured_llm = llm.with_structured_output(GraphMappingSpec, **method)

    if verbose:
        print("🚀 Generating field mappings...\n")

    # Generate mapping
    from langchain_core.messages import SystemMessage, HumanMessage

    try:
        mapping_spec = await structured_llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_message)
        ])
    except (GroqRateLimitError, GroqBadRequestError, OpenAIBadRequestError):
        raise

    if verbose:
        print("✅ MAPPING GENERATED")
        print("=" * 80)
        print("\n📋 Field Mappings:")
        for mapping in mapping_spec.field_mappings:
            print(f"  {mapping.graph_field} ← {mapping.dataframe_column}")
            print(f"    └─ {mapping.description}")

        print("\n🎨 Metadata Configuration:")
        print(f"  Title: {mapping_spec.metadata_config.title}")
        if mapping_spec.metadata_config.x_axis_label:
            print(f"  X-Axis: {mapping_spec.metadata_config.x_axis_label}")
        if mapping_spec.metadata_config.y_axis_label:
            print(f"  Y-Axis: {mapping_spec.metadata_config.y_axis_label}")
        print(f"  Legend: {mapping_spec.metadata_config.show_legend}")
        print(f"  Color Scheme: {mapping_spec.metadata_config.color_scheme}")

        print(f"\n💡 Reasoning: {mapping_spec.reasoning}")
        print("=" * 80 + "\n")

    return mapping_spec


# ============================================================================
# CONVENIENCE FUNCTION
# ============================================================================

async def map_dataframe_to_graph(
    df: pd.DataFrame,
    user_query: str,
    chart_type: str,
    owner_id: Optional[str] = None,
    model: str = None,
    provider: Optional[str] = None,
    verbose: bool = True,
    custom_instruction: str = None,
    model_config: Optional[Dict[str, Any]] = None
) -> GraphMappingSpec:
    """
    Convenience function that extracts schema and generates mapping.

    Args:
        df: Transformed DataFrame
        user_query: User's original query
        chart_type: Type of chart to generate
        owner_id: Owner ID for credential lookup
        model: LLM model to use
        verbose: Print progress
        custom_instruction: Optional custom instruction

    Returns:
        GraphMappingSpec with field mappings and metadata
    """
    # Extract schema (no data values)
    schema = extract_dataframe_schema(df)

    # Generate mapping
    mapping = await generate_graph_mapping(
        df_schema=schema,
        user_query=user_query,
        chart_type=chart_type,
        owner_id=owner_id,
        model=model,
        provider=provider,
        verbose=verbose,
        custom_instruction=custom_instruction
    )

    return mapping
