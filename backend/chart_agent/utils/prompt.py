# Additional chart-type specific instructions to guide the LLM
GRAPH_TYPE_INSTRUCTIONS = {
    "Bar Chart": (
        "Use a categorical x-axis with labels and a numeric y-axis with values. "
        "Ensure each category appears once unless explicitly grouping. "
        "REQUIRED fields: data[].category, data[].value, metadata.title, metadata.x_axis.label, metadata.y_axis.label, "
        "metadata.legend.show, metadata.colors (list of hex colors). Do not omit any required fields; produce valid tool args."
    ),
    "Column Chart": (
        "Use a categorical x-axis with labels and a numeric y-axis with values. "
        "Ensure each category appears once unless explicitly grouping. "
        "REQUIRED fields: data[].category, data[].value, metadata.title, metadata.x_axis.label, metadata.y_axis.label, "
        "metadata.legend.show, metadata.colors (list of hex colors). Do not omit any required fields; produce valid tool args."
    ),
    "Pie Chart": (
        "Include slice labels and numeric values. Percentages should be clear and sum to ~100%. "
        "Avoid too many tiny slices; merge minor ones under 'Other' if needed. "
        "REQUIRED fields: data[].label, data[].value, metadata.title, metadata.legend.show, metadata.colors (list of hex colors). "
        "Do not omit any required fields; produce valid tool args."
    ),
    "Line Chart": (
        "Ensure at least two data points for a meaningful line. Order points by the x-axis. "
        "The x-axis should be temporal or ordered categories. Avoid nulls. "
        "REQUIRED fields: data[].x, data[].y, metadata.title, metadata.x_axis.label, metadata.y_axis.label, metadata.legend.show. "
        "Do not omit any required fields; produce valid tool args."
    ),
    "Stacked Bar Chart": (
        "Provide segments per bar where segment category names exactly match the colors mapping keys. "
        "Clearly indicate stack type ('normal' or 'percent'). "
        "CRITICAL: Include an entry in the data array for EVERY row in the raw data. Do NOT sample, truncate, or omit any rows. "
        "REQUIRED fields: data[].index, data[].segments[].category, data[].segments[].value, "
        "metadata.title, metadata.x_axis.label, metadata.y_axis.label, metadata.legend.show, "
        "metadata.colors (mapping of EVERY segment category to hex color), metadata.stack_type, metadata.chart_orientation. "
        "Segment categories MUST exactly match keys in metadata.colors. Do not omit any required fields; produce valid tool args."
    ),
    "Bubble Chart": (
        "Provide numeric x, y, and positive size values for each bubble. Include a label for tooltips. "
        "REQUIRED fields: data[].x, data[].y, data[].size, data[].label, metadata.title, metadata.x_axis.label, metadata.y_axis.label, "
        "metadata.size_axis.label, metadata.colors (list of hex colors), metadata.legend.show. Do not omit any required fields; produce valid tool args."
    ),
    "Geo Chart": (
        "The first row must be a header row. Include a 'Country' column with a 3-letter ISO code (e.g., USA, JPN, AUS) in every data row. "
        "REQUIRED fields: data[0] header row present, metadata.title, metadata.region, metadata.color_axis.colors (list of hex colors), "
        "metadata.legend.show, metadata.tooltip.show. Do not omit any required fields; produce valid tool args."
    ),
    "Scatter Chart": (
        "Provide equal-length numeric arrays for x and y. Optionally include a trend line and point styling. "
        "REQUIRED fields: data.x (list), data.y (list) with equal lengths, metadata.title, metadata.x_axis.label, metadata.y_axis.label, metadata.legend.show. "
        "Do not omit any required fields; produce valid tool args."
    ),
}

# Base system prompt templates
SUGGEST_CHART_SYSTEM_PROMPT = (
    "You are an expert data analyst. Given the user's question, suggest the most suitable chart type "
    "from this list: {chart_list}.\n\n"
    "CHART SELECTION GUIDELINES:\n"
    "- **Stacked Bar Chart**: Use when the query involves **multiple metrics**, **grouping**, **sub-categories**, or **segmentation** "
    "This is the most robust choice for multi-dimensional data.\n"
    "- **Bar Chart / Column Chart**: Use for single metric categorical comparisons.\n"
    "- **Line Chart**: Use ONLY for showing a **single continuous trend over time**. "
    "CRITICAL: If the user asks for a 'grouped' or 'segmented' view, do NOT suggest a Line Chart; suggest a Stacked Bar Chart instead.\n"
    "- **Pie Chart**: Use for part-to-whole relationships with a single metric. Avoid if more than 6 categories.\n"
    "- **Scatter Chart**: Use for correlation between two numeric variables.\n"
    "- **Bubble Chart**: Use for 3 numeric variables (x, y, size).\n"
    "- **Geo Chart**: Use for geographic data (Country ISO codes).\n\n"
    "DECISION LOGIC:\n"
    "1. Does it have grouping or multiple metrics? -> Stacked Bar Chart.\n"
    "2. Is it a single metric over time? -> Line Chart.\n"
    "3. Is it a simple comparison of categories? -> Bar Chart.\n\n"
    "Respond ONLY with the chart type name."
)

GENERATE_GRAPH_SYSTEM_PROMPT = (
    "You are an expert data analyst. Given the user's question and the raw data, generate the chart data and metadata. "
    "Follow the chart-specific rules for {chart_type}. {extra_rules}\n"
    "CRITICAL: Do not omit any required fields from the schema. Produce valid tool/function call arguments that fully satisfy the schema. "
    "If a required field is not explicit in raw_data, infer a sensible value consistent with the question and chart type. "
    "For Stacked Bar Charts, ensure 'metadata.colors' is a dictionary mapping *every* segment category name to a hex color code, e.g., `{'Digital Nomads': '#FF5733', 'Corporate Immigration': '#33FF57'}`. "
    "Output must follow the provided JSON schema.\n\n"
    "COMMON METADATA REQUIREMENTS (APPLY TO ALL CHART TYPES):\n"
    "- metadata.title: human-readable chart title (string)\n"
    "- metadata.subtitle: optional short subtitle (string)\n"
    "- metadata.x_axis.label: label for the x-axis when applicable (string)\n"
    "- metadata.y_axis.label: label for the y-axis when applicable (string)\n"
    "- metadata.legend.show: whether to show the legend (boolean)\n"
    "- metadata.legend.position: one of 'top', 'bottom', 'left', 'right' (string)\n"
    "- metadata.tooltip.show: whether tooltips should be enabled (boolean)\n"
    "- metadata.colors: either a list of hex color strings (['#rrggbb', ...]) for single-series charts, OR a dictionary mapping every category/segment name used in the data to a hex color (e.g., {'Category A':'#rrggbb', ...}).\n"
    "  - All hex colors MUST be in the format '#RRGGBB' (lower or upper case acceptable).\n"
    "  - For stacked/multi-segment charts the mapping MUST include an entry for every segment category.\n"
    "- metadata.chart_orientation: 'vertical' or 'horizontal' when applicable (string)\n"
    "- metadata.stack_type: for stacked charts, either 'normal' or 'percent' (string)\n"
    "- metadata.chart_type: the canonical chart type name (string)\n\n"
    "STRICT RULES:\n"
    "- Segment/category names in the data MUST exactly match keys in metadata.colors when a mapping is required.\n"
    "- Never return color names or short codes; always use full hex codes.\n"
    "- Do not include any plotting code or imports; return only the data and metadata objects.\n"
    "Output must follow the provided JSON schema."
)





"""
Chart-specific requirements for transformation and mapping.

This file contains the schema requirements for each chart type.
Used by both the transformation agent and mapping agent.
"""

# Requirements for transformation agent (output schema)
TRANSFORMATION_REQUIREMENTS = {
    "Stacked Bar Chart": "The final DataFrame MUST have: 'index' (the main category/time axis), 'segment_category' (the grouping dimension), and 'segment_value' (the metric). If the raw data has multiple metrics to compare, you MUST melt them into this long format where 'segment_category' contains the metric names and 'segment_value' contains their values.",
    "Bar Chart": "Final DataFrame MUST have: 'category' (labels), 'value' (numeric).",
    "Column Chart": "Final DataFrame MUST have: 'category' (labels), 'value' (numeric).",
    "Pie Chart": "Final DataFrame MUST have: 'label' (slice names), 'value' (numeric).",
    "Line Chart": "Final DataFrame MUST have: 'x' (sequential/time), 'y' (numeric).",
    "Bubble Chart": "Final DataFrame MUST have: 'x' (numeric), 'y' (numeric), 'size' (numeric), 'label' (string).",
    "Scatter Chart": "Final DataFrame MUST have: 'x' (numeric), 'y' (numeric).",
    "Geo Chart": "Final DataFrame MUST have: 'country' (3-letter ISO country code, e.g. USA/JPN/AUS — uppercase), 'value' (numeric). Ensure all country codes are exactly 3 uppercase letters.",
}

# Requirements for mapping agent (field mappings)
MAPPING_FIELD_REQUIREMENTS = {
    "Bar Chart": [
        {"field": "category", "type": "string", "description": "Labels for bars"},
        {"field": "value", "type": "numeric", "description": "Numerical values for bar heights"}
    ],
    "Column Chart": [
        {"field": "category", "type": "string", "description": "Labels for columns"},
        {"field": "value", "type": "numeric", "description": "Numerical values for column heights"}
    ],
    "Pie Chart": [
        {"field": "label", "type": "string", "description": "Labels for pie slices"},
        {"field": "value", "type": "numeric", "description": "Numerical values for slice sizes"}
    ],
    "Line Chart": [
        {"field": "x", "type": "string or numeric", "description": "X-axis values (time, date, or category)"},
        {"field": "y", "type": "numeric", "description": "Y-axis values (measurements)"}
    ],
    "Stacked Bar Chart": [
        {"field": "index", "type": "string", "description": "Main category labels (e.g., weeks, quarters)"},
        {"field": "segment_category", "type": "string", "description": "Sub-category for stacks (e.g., product types)"},
        {"field": "segment_value", "type": "numeric", "description": "Numerical values for each segment"}
    ],
    "Bubble Chart": [
        {"field": "x", "type": "numeric", "description": "X-axis numerical value"},
        {"field": "y", "type": "numeric", "description": "Y-axis numerical value"},
        {"field": "size", "type": "numeric", "description": "Bubble size (numerical)"},
        {"field": "label", "type": "string", "description": "Bubble labels"}
    ],
    "Scatter Chart": [
        {"field": "x", "type": "numeric", "description": "X-axis numerical value"},
        {"field": "y", "type": "numeric", "description": "Y-axis numerical value"}
    ],
    "Geo Chart": [
        {"field": "country", "type": "string", "description": "3-letter ISO country code (e.g., USA, JPN, AUS)"},
        {"field": "value", "type": "numeric", "description": "Numeric value to display as a geographic heatmap"}
    ],
}


def get_transformation_requirement(chart_type: str) -> str:
    """Get transformation requirement for a specific chart type"""
    return TRANSFORMATION_REQUIREMENTS.get(chart_type, "")


def get_mapping_requirements(chart_type: str) -> list:
    """Get mapping field requirements for a specific chart type"""
    return MAPPING_FIELD_REQUIREMENTS.get(chart_type, [])




"""
Prompt template for the graph mapping agent.

This file contains the system prompt used by the mapping agent LLM.
The mapping agent takes a DataFrame schema and maps columns to graph fields.
"""

MAPPING_AGENT_PROMPT = """You are a data visualization mapping specialist. Your job is to map DataFrame columns to graph fields for a {chart_type}.

**CRITICAL: You will ONLY see the DataFrame SCHEMA - column names and data types.**
**You will NOT see any actual data values. Do not make assumptions about data content.**

**YOUR TASK:**
Map DataFrame columns to the required graph fields based solely on:
1. Column names (which should be descriptive)
2. Data types (numeric, string, datetime, etc.)
3. User's query (what they want to visualize)

**REQUIRED FIELDS FOR {chart_type_upper}:**
{requirements_str}

**MAPPING RULES:**

1. **Match by semantic meaning:**
   - Column named 'Week' or 'Date' → likely x-axis or index
   - Column named 'Revenue' or 'Sales' → likely value or y-axis
   - Column named 'Country' or 'Product' → likely category or label

2. **Match by data type:**
   - Numeric columns → value, y, size fields
   - String columns → category, label, index fields
   - Datetime columns → x-axis for time series

3. **One-to-one mapping:**
   - Each graph field should map to exactly ONE DataFrame column
   - Each DataFrame column should be used at most once (unless chart allows it)

4. **Consider user intent:**
   - User query provides context about what to visualize
   - Map columns that fulfill the user's request

**METADATA CONFIGURATION:**

Generate appropriate metadata:
- **Title**: Create from user query (concise, descriptive)
- **Axis labels**: Use clear, readable labels based on column names
- **Legend**: Show legend if there are multiple series/categories
- **Colors**: Suggest a color scheme (default, warm, cool, monochrome)

{custom_instruction_section}

**IMPORTANT:**
- Map based on column names and types ONLY
- Do not invent or assume data values
- If unsure, choose the most semantically appropriate column"""


def get_custom_instruction_section(custom_instruction: str = None) -> str:
    """Generate the custom instruction section for the prompt"""
    if not custom_instruction:
        return ""

    return f"""

**CUSTOM INSTRUCTION:**
{custom_instruction}

IMPORTANT: You MUST follow the custom instruction above when generating field mappings and metadata configuration."""


"""
Prompt template for the transformation agent.

This file contains the system prompt used by the transformation agent LLM.
Keeping it separate makes the prompt easier to maintain and test.
"""

TRANSFORMATION_AGENT_PROMPT = """You are a data transformation specialist. Your job is to write ONE comprehensive pandas transformation to prepare a transformed dataframe that can be used to create a {chart_type}.

**CURRENT DATETIME:**
{current_datetime}

**USER'S REQUEST:**
{user_query}{custom_instruction_section}

**YOUR WORKFLOW (3 steps only):**

Step 1: Call `inspect_dataframe()` to see the current DataFrame structure

Step 2: Call `execute_transformation(pandas_code, description)` with your COMPLETE transformation
   - Write ALL transformation logic in one code block
   - Input: df (current DataFrame)
   - Output: df_final (transformed DataFrame)
   - Can use intermediate variables
   - Can be multi-line with comments

Step 3: Call `finish_transformation(reasoning)` to confirm completion

**TRANSFORMATION CODE REQUIREMENTS:**

1. **Input/Output:**
   - Input: 'df' variable (current DataFrame)
   - Output: 'df_final' variable (MUST create this)

2. **Available:**
   - pd (pandas)
   - np (numpy)
   - df (input DataFrame)

3. **NOT Available:**
   - matplotlib, plotly, seaborn
   - External APIs or databases
   - File I/O operations

**CRITICAL:**
- Write the COMPLETE transformation in ONE execute_transformation call
- Your code MUST create 'df_final' variable
- {chart_requirements}

Start by calling inspect_dataframe()!"""


def get_custom_instruction_section(custom_instruction: str = None) -> str:
    """Generate the custom instruction section for the prompt"""
    if not custom_instruction:
        return ""

    return f"""

**CUSTOM INSTRUCTION:**
{custom_instruction}

IMPORTANT: You MUST follow the custom instruction above when performing the transformation."""



ROUTER_SYSTEM_PROMPT = """You are a routing assistant. Analyze the user's query and determine if it requires:
1. Data processing, CSV analysis, or graph/chart generation → needs_data_processing = True
2. Simple conversation, greetings, or general questions → needs_data_processing = False

Examples:
- "Hi" → False (greeting)
- "What can you do?" → False (general question)
- "Show me sales trends" → True (needs data/graph)
- "Create a bar chart of revenue" → True (needs data/graph)
- "Analyze the CSV file" → True (needs data processing)
- "How are you?" → False (conversation)

Be smart: only route to data processing if the query actually needs CSV/data work."""