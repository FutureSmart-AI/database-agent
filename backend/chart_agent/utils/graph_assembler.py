"""
Graph Data Assembler

This module takes:
1. Transformed DataFrame (with actual data)
2. Field mappings (from graph_mapper)
3. Target chart type

And produces:
- Complete graph data structure with actual values
- Populated metadata with colors, legends, etc.

This is a pure Python function - no LLM calls.
"""

import pandas as pd
from typing import Any, Dict, List, Optional, Tuple
from logger import logger


# ============================================================================
# COLOR SCHEMES
# ============================================================================

COLOR_SCHEMES = {
    "default": [
        "#3498db", "#e74c3c", "#2ecc71", "#f39c12", "#9b59b6",
        "#1abc9c", "#34495e", "#e67e22", "#95a5a6", "#c0392b"
    ],
    "warm": [
        "#ff6b6b", "#ff8c42", "#ffd93d", "#6bcf7f", "#4ecdc4",
        "#ff4757", "#ff6348", "#ffa502", "#ff7f50", "#ff6347"
    ],
    "cool": [
        "#4facfe", "#00f2fe", "#43e97b", "#38f9d7", "#667eea",
        "#764ba2", "#667eea", "#f093fb", "#4facfe", "#00f2fe"
    ],
    "monochrome": [
        "#2c3e50", "#34495e", "#7f8c8d", "#95a5a6", "#bdc3c7",
        "#ecf0f1", "#34495e", "#2c3e50", "#7f8c8d", "#95a5a6"
    ]
}


def get_colors(color_scheme: str, num_colors: int) -> List[str]:
    """Get a list of colors from a color scheme"""
    colors = COLOR_SCHEMES.get(color_scheme, COLOR_SCHEMES["default"])

    # If we need more colors than available, cycle through them
    if num_colors <= len(colors):
        return colors[:num_colors]
    else:
        # Repeat the color scheme
        repeated = (colors * ((num_colors // len(colors)) + 1))
        return repeated[:num_colors]


# ============================================================================
# BAR/COLUMN CHART DATA ASSEMBLY
# ============================================================================

def assemble_bar_column_chart(
    df: pd.DataFrame,
    field_mappings: Dict[str, str],
    metadata_config: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Assemble data for Bar or Column Chart.

    Required mappings:
        - category: string column
        - value: numeric column
    """
    category_col = field_mappings.get("category")
    value_col = field_mappings.get("value")

    if not category_col or not value_col:
        raise ValueError("Bar/Column chart requires 'category' and 'value' mappings")

    # Build data items
    data = []
    for _, row in df.iterrows():
        data.append({
            "category": str(row[category_col]),
            "value": float(row[value_col])
        })

    # Get colors
    num_bars = len(data)
    colors = get_colors(metadata_config.get("color_scheme", "default"), num_bars)

    # Build metadata
    metadata = {
        "title": metadata_config.get("title", "Chart"),
        "x_axis": {
            "label": metadata_config.get("x_axis_label", category_col),
            "field": category_col
        },
        "y_axis": {
            "label": metadata_config.get("y_axis_label", value_col),
            "field": value_col
        },
        "legend": {
            "show": metadata_config.get("show_legend", False),
            "position": metadata_config.get("legend_position", "right")
        },
        "colors": colors
    }

    return {
        "data": data,
        "metadata": metadata
    }


# ============================================================================
# PIE CHART DATA ASSEMBLY
# ============================================================================

def assemble_pie_chart(
    df: pd.DataFrame,
    field_mappings: Dict[str, str],
    metadata_config: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Assemble data for Pie Chart.

    Required mappings:
        - label: string column
        - value: numeric column
    """
    label_col = field_mappings.get("label")
    value_col = field_mappings.get("value")

    if not label_col or not value_col:
        raise ValueError("Pie chart requires 'label' and 'value' mappings")

    # Build data items
    data = []
    for _, row in df.iterrows():
        data.append({
            "label": str(row[label_col]),
            "value": float(row[value_col])
        })

    # Get colors
    num_slices = len(data)
    colors = get_colors(metadata_config.get("color_scheme", "default"), num_slices)

    # Build metadata
    metadata = {
        "title": metadata_config.get("title", "Pie Chart"),
        "legend": {
            "show": metadata_config.get("show_legend", True),
            "position": metadata_config.get("legend_position", "right")
        },
        "colors": colors,
        "show_percentages": True  # Default to True
    }

    return {
        "data": data,
        "metadata": metadata
    }


# ============================================================================
# LINE CHART DATA ASSEMBLY
# ============================================================================

def assemble_line_chart(
    df: pd.DataFrame,
    field_mappings: Dict[str, str],
    metadata_config: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Assemble data for Line Chart.

    Required mappings:
        - x: string/numeric/datetime column
        - y: numeric column
    """
    x_col = field_mappings.get("x")
    y_col = field_mappings.get("y")

    if not x_col or not y_col:
        raise ValueError("Line chart requires 'x' and 'y' mappings")

    # Build data items
    data = []
    for _, row in df.iterrows():
        x_val = row[x_col]
        # Convert to string if datetime
        if pd.api.types.is_datetime64_any_dtype(df[x_col]):
            x_val = str(x_val)

        data.append({
            "x": x_val,
            "y": float(row[y_col])
        })

    # Get color
    colors = get_colors(metadata_config.get("color_scheme", "default"), 1)

    # Build metadata
    metadata = {
        "title": metadata_config.get("title", "Line Chart"),
        "x_axis": {
            "label": metadata_config.get("x_axis_label", x_col),
            "field": x_col
        },
        "y_axis": {
            "label": metadata_config.get("y_axis_label", y_col),
            "field": y_col
        },
        "line": {
            "color": colors[0],
            "width": 2,
            "smooth": True  # Default to True
        },
        "legend": {
            "show": metadata_config.get("show_legend", False),
            "position": metadata_config.get("legend_position", "top")
        }
    }

    return {
        "data": data,
        "metadata": metadata
    }


# ============================================================================
# STACKED BAR CHART DATA ASSEMBLY
# ============================================================================

def assemble_stacked_bar_chart(
    df: pd.DataFrame,
    field_mappings: Dict[str, Any],
    metadata_config: Dict[str, Any]
) -> Dict[str, Any]:
    """Assemble data for Stacked Bar Chart."""
    index_col = field_mappings.get("index")
    segment_cat_col = field_mappings.get("segment_category")
    segment_val_col = field_mappings.get("segment_value")

    # Handle wide format: multiple segment_value columns (column names are categories)
    if isinstance(segment_val_col, list):
        # Wide format: we have multiple segment_value columns
        if not index_col or not segment_val_col:
            raise ValueError("Stacked bar chart requires 'index' and at least one 'segment_value' mapping")
        
        # Column names are the segment categories
        segment_columns = segment_val_col
        
        # Build data: one bar per index value
        data = []
        for _, row in df.iterrows():
            index_val = str(row[index_col])
            
            segments = []
            for segment_col in segment_columns:
                if segment_col in df.columns:
                    segments.append({
                        "category": segment_col,  # Column name is the category
                        "value": float(row[segment_col])
                    })
            
            data.append({
                "index": index_val,
                "segments": segments
            })
        
        # Get unique segment categories from column names
        unique_segments = segment_columns
        colors_list = get_colors(metadata_config.get("color_scheme", "default"), len(unique_segments))
        
        # Build color mapping using column names
        colors = {str(seg): color for seg, color in zip(unique_segments, colors_list)}
        
        # Build metadata
        legend_title = segment_cat_col if segment_cat_col else "Segment"
        y_axis_label = metadata_config.get("y_axis_label", "Value")
        
        metadata = {
            "title": metadata_config.get("title", "Stacked Bar Chart"),
            "x_axis": {
                "label": metadata_config.get("x_axis_label", index_col),
                "field": index_col
            },
            "y_axis": {
                "label": y_axis_label,
                "field": "value"
            },
            "legend": {
                "show": metadata_config.get("show_legend", True),
                "position": metadata_config.get("legend_position", "right"),
                "title": legend_title
            },
            "colors": colors,
            "stack_type": "normal",  # Default
            "chart_orientation": "horizontal"  # Default
        }
        
        return {
            "data": data,
            "metadata": metadata
        }
    
    # Long format: traditional segment_category + segment_value columns
    if not all([index_col, segment_cat_col, segment_val_col]):
        raise ValueError("Stacked bar chart requires 'index', 'segment_category', and 'segment_value' mappings")

    # Group by index to build bars
    data = []
    for index_val in df[index_col].unique():
        segments_df = df[df[index_col] == index_val]

        segments = []
        for _, row in segments_df.iterrows():
            segments.append({
                "category": str(row[segment_cat_col]),
                "value": float(row[segment_val_col])
            })

        data.append({
            "index": str(index_val),
            "segments": segments
        })

    # Get unique segment categories for colors
    unique_segments = df[segment_cat_col].unique()
    colors_list = get_colors(metadata_config.get("color_scheme", "default"), len(unique_segments))

    # Build color mapping
    colors = {str(seg): color for seg, color in zip(unique_segments, colors_list)}

    # Build metadata
    metadata = {
        "title": metadata_config.get("title", "Stacked Bar Chart"),
        "x_axis": {
            "label": metadata_config.get("x_axis_label", index_col),
            "field": index_col
        },
        "y_axis": {
            "label": metadata_config.get("y_axis_label", segment_val_col),
            "field": segment_val_col
        },
        "legend": {
            "show": metadata_config.get("show_legend", True),
            "position": metadata_config.get("legend_position", "right"),
            "title": segment_cat_col
        },
        "colors": colors,
        "stack_type": "normal",  # Default
        "chart_orientation": "horizontal"  # Default
    }

    return {
        "data": data,
        "metadata": metadata
    }


# ============================================================================
# BUBBLE CHART DATA ASSEMBLY
# ============================================================================

def assemble_bubble_chart(
    df: pd.DataFrame,
    field_mappings: Dict[str, str],
    metadata_config: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Assemble data for Bubble Chart.

    Required mappings:
        - x: numeric column
        - y: numeric column
        - size: numeric column
        - label: string column
    """
    x_col = field_mappings.get("x")
    y_col = field_mappings.get("y")
    size_col = field_mappings.get("size")
    label_col = field_mappings.get("label")

    if not all([x_col, y_col, size_col, label_col]):
        raise ValueError("Bubble chart requires 'x', 'y', 'size', and 'label' mappings")

    # Build data items
    data = []
    for _, row in df.iterrows():
        data.append({
            "x": float(row[x_col]),
            "y": float(row[y_col]),
            "size": float(row[size_col]),
            "label": str(row[label_col])
        })

    # Get colors
    num_bubbles = len(data)
    colors = get_colors(metadata_config.get("color_scheme", "default"), num_bubbles)

    # Build metadata
    metadata = {
        "title": metadata_config.get("title", "Bubble Chart"),
        "x_axis": {
            "label": metadata_config.get("x_axis_label", x_col),
            "field": x_col
        },
        "y_axis": {
            "label": metadata_config.get("y_axis_label", y_col),
            "field": y_col
        },
        "size_axis": {
            "label": size_col,
            "min_size": 10,
            "max_size": 50
        },
        "colors": colors,
        "legend": {
            "show": metadata_config.get("show_legend", True),
            "position": metadata_config.get("legend_position", "right")
        }
    }

    return {
        "data": data,
        "metadata": metadata
    }


# ============================================================================
# SCATTER CHART DATA ASSEMBLY
# ============================================================================

def assemble_scatter_chart(
    df: pd.DataFrame,
    field_mappings: Dict[str, str],
    metadata_config: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Assemble data for Scatter Chart.

    Required mappings:
        - x: numeric column
        - y: numeric column
    """
    x_col = field_mappings.get("x")
    y_col = field_mappings.get("y")

    if not x_col or not y_col:
        raise ValueError("Scatter chart requires 'x' and 'y' mappings")

    # Build data payload
    data = {
        "x": df[x_col].tolist(),
        "y": df[y_col].tolist()
    }

    # Get color
    colors = get_colors(metadata_config.get("color_scheme", "default"), 1)

    # Build metadata
    metadata = {
        "title": metadata_config.get("title", "Scatter Chart"),
        "x_axis": {
            "label": metadata_config.get("x_axis_label", x_col),
            "field": x_col
        },
        "y_axis": {
            "label": metadata_config.get("y_axis_label", y_col),
            "field": y_col
        },
        "point": {
            "color": colors[0],
            "size": 8
        },
        "trend_line": {
            "show": False,  # Default to False
            "color": colors[0]
        },
        "legend": {
            "show": metadata_config.get("show_legend", False)
        }
    }

    return {
        "data": data,
        "metadata": metadata
    }


# ============================================================================
# CHART TYPE STRUCTURAL VALIDATOR
# ============================================================================

def plotted_measure_columns(df: pd.DataFrame, measure_columns: List[str] | None = None) -> List[str]:
    """Numeric columns the chart plots: the mapping's measures when it named any, else every numeric column."""
    numeric = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    if measure_columns:
        named = [c for c in measure_columns if c in numeric]
        if named:
            return named
    return numeric


def combine_label_columns(
    df: pd.DataFrame,
    field_mappings: List[Dict[str, str]],
    label_columns: List[str] | None = None,
) -> tuple:
    """
    Join a multi-column item name (e.g. first_name + last_name) into one label column.

    The mapping model maps the label field to the first label column; this
    repoints that mapping to the joined column so each item gets one full label
    instead of the second name part becoming a stack segment or being dropped.
    Returns (df, field_mappings), unchanged when there is a single label column.
    """
    cols = [c for c in (label_columns or []) if c in df.columns]
    if len(cols) < 2:
        return df, field_mappings
    joined = "_".join(cols)
    while joined in df.columns:
        joined = f"{joined}_label"
    df = df.copy()
    df[joined] = df[cols].astype(str).agg(" ".join, axis=1)
    remapped = [
        {**m, "dataframe_column": joined} if m["dataframe_column"] == cols[0] else m
        for m in field_mappings
        if m["dataframe_column"] not in cols[1:]
    ]
    return df, remapped


def infer_correct_chart_type(
    df: pd.DataFrame,
    current_chart_type: str,
    allowed_graphs: List[str] | None = None,
    measure_columns: List[str] | None = None,
    label_columns: List[str] | None = None,
) -> tuple:
    """
    Validates the actual DataFrame structure against the selected chart type.
    Returns (corrected_chart_type, reason_string_or_None).

    reason is None when no correction is needed.
    When a correction is made, reason explains WHY so it can be logged clearly.

    Which columns are plotted quantities is a semantic call made by the mapping
    model (measure_columns); identifiers such as `id` are numeric but are not
    series. The rules below only count those measures. Without a measure list
    every numeric column is counted.
    """
    numeric_cols = plotted_measure_columns(df, measure_columns)
    # A name split over several columns (first_name, last_name) is one dimension, not two.
    labels = [c for c in (label_columns or []) if c in df.columns]
    non_numeric_cols = [
        c for c in df.columns
        if not pd.api.types.is_numeric_dtype(df[c]) and c not in labels[1:]
    ]
    n_numeric = len(numeric_cols)
    n_rows = len(df)

    def is_allowed(chart_type: str) -> bool:
        if not allowed_graphs:
            return True
        return chart_type in allowed_graphs

    def best_allowed(*candidates: str) -> str:
        for c in candidates:
            if is_allowed(c):
                return c
        return current_chart_type  # keep original if none of the candidates are allowed

    # --- Line / Bar / Column: multiple numeric columns = multiple series ---
    if current_chart_type in ("Line Chart", "Bar Chart", "Column Chart"):
        if n_numeric > 1:
            corrected = best_allowed("Stacked Bar Chart", "Bar Chart", "Column Chart")
            if corrected != current_chart_type:
                return corrected, (
                    f"{current_chart_type} cannot represent {n_numeric} numeric columns "
                    f"({', '.join(numeric_cols)}) — data has multiple series. "
                    f"Auto-corrected to {corrected}."
                )

    # --- Pie Chart: too many slices or multiple series ---
    if current_chart_type == "Pie Chart":
        if n_rows > 8:
            corrected = best_allowed("Bar Chart", "Column Chart", "Stacked Bar Chart")
            if corrected != current_chart_type:
                return corrected, (
                    f"Pie Chart requires ≤8 slices but data has {n_rows} rows. "
                    f"Auto-corrected to {corrected}."
                )
        if n_numeric > 1:
            corrected = best_allowed("Bar Chart", "Column Chart", "Stacked Bar Chart")
            if corrected != current_chart_type:
                return corrected, (
                    f"Pie Chart cannot represent {n_numeric} numeric columns — single metric required. "
                    f"Auto-corrected to {corrected}."
                )

    # --- Scatter Chart: needs exactly 2 numeric columns ---
    if current_chart_type == "Scatter Chart":
        if n_numeric < 2:
            corrected = best_allowed("Bar Chart", "Column Chart")
            if corrected != current_chart_type:
                return corrected, (
                    f"Scatter Chart needs 2 numeric columns but data only has {n_numeric}. "
                    f"Auto-corrected to {corrected}."
                )

    # --- Bubble Chart: needs 3+ numeric columns ---
    if current_chart_type == "Bubble Chart":
        if n_numeric < 3:
            if n_numeric >= 2:
                corrected = best_allowed("Scatter Chart", "Bar Chart", "Column Chart")
            else:
                corrected = best_allowed("Bar Chart", "Column Chart")
            if corrected != current_chart_type:
                return corrected, (
                    f"Bubble Chart needs 3 numeric columns (x, y, size) but data only has {n_numeric}. "
                    f"Auto-corrected to {corrected}."
                )

    # --- Stacked Bar Chart: needs at least 1 numeric and multiple columns ---
    if current_chart_type == "Stacked Bar Chart":
        if n_numeric == 0:
            corrected = best_allowed("Bar Chart", "Column Chart")
            if corrected != current_chart_type:
                return corrected, (
                    f"Stacked Bar Chart needs numeric columns but none found. "
                    f"Auto-corrected to {corrected}."
                )
        if n_numeric == 1 and len(non_numeric_cols) <= 1:
            corrected = best_allowed("Bar Chart", "Column Chart")
            if corrected != current_chart_type:
                return corrected, (
                    f"Stacked Bar Chart needs multiple series but data only has 1 numeric column. "
                    f"Auto-corrected to {corrected}."
                )

    return current_chart_type, None  # no correction needed


# ============================================================================
# GEO CHART DATA ASSEMBLY
# ============================================================================

def assemble_geo_chart(
    df: pd.DataFrame,
    field_mappings: Dict[str, str],
    metadata_config: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Assemble data for Geo Chart.

    Required mappings:
        - country: string column with 3-letter ISO codes
        - value: numeric column
    """
    country_col = field_mappings.get("country")
    value_col = field_mappings.get("value")

    if not country_col or not value_col:
        raise ValueError("Geo chart requires 'country' and 'value' mappings")

    # GeoChart data format: first row is header, subsequent rows are data
    header = [country_col, value_col, "Country"]
    data: List[Any] = [header]
    for _, row in df.iterrows():
        data.append([str(row[country_col]).upper(), float(row[value_col]), str(row[country_col]).upper()])

    colors = get_colors(metadata_config.get("color_scheme", "default"), 3)

    metadata = {
        "title": metadata_config.get("title", "Geo Chart"),
        "region": "world",
        "color_axis": {
            "min_value": 0,
            "colors": colors
        },
        "legend": {
            "show": metadata_config.get("show_legend", True),
            "position": metadata_config.get("legend_position", "bottom"),
        },
        "tooltip": {"show": True}
    }

    return {"data": data, "metadata": metadata}


# ============================================================================
# MASTER ASSEMBLY FUNCTION
# ============================================================================

ASSEMBLERS = {
    "Bar Chart": assemble_bar_column_chart,
    "Column Chart": assemble_bar_column_chart,
    "Pie Chart": assemble_pie_chart,
    "Line Chart": assemble_line_chart,
    "Stacked Bar Chart": assemble_stacked_bar_chart,
    "Bubble Chart": assemble_bubble_chart,
    "Scatter Chart": assemble_scatter_chart,
    "Geo Chart": assemble_geo_chart,
}


def assemble_graph_data(
    df: pd.DataFrame,
    chart_type: str,
    field_mappings: List[Dict[str, str]],
    metadata_config: Dict[str, Any],
    verbose: bool = True
) -> Dict[str, Any]:
    """
    Master function to assemble complete graph data from DataFrame and mappings.

    Args:
        df: Transformed DataFrame with actual data
        chart_type: Type of chart
        field_mappings: List of field mappings from graph_mapper
        metadata_config: Metadata configuration from graph_mapper
        verbose: Print progress

    Returns:
        Complete graph data dictionary ready for response
    """
    if verbose:
        logger.info("=" * 80)
        logger.info("ASSEMBLING GRAPH DATA")
        logger.info("=" * 80)
        logger.info(f"Chart Type (raw): {chart_type}")
        logger.info(f"📁 DataFrame Shape: {df.shape}")
        logger.info("=" * 80)

    # Convert field_mappings list to dict
    # Handle multiple mappings with the same graph_field (e.g., multiple segment_value)
    mappings_dict = {}
    for mapping in field_mappings:
        graph_field = mapping["graph_field"]
        df_col = mapping["dataframe_column"]
        
        # If we already have this graph_field, store as a list
        if graph_field in mappings_dict:
            existing = mappings_dict[graph_field]
            if isinstance(existing, list):
                existing.append(df_col)
            else:
                mappings_dict[graph_field] = [existing, df_col]
        else:
            mappings_dict[graph_field] = df_col

    if verbose:
        logger.info("Field Mappings:")
        for graph_field, df_col in mappings_dict.items():
            if isinstance(df_col, list):
                for col in df_col:
                    logger.info(f"  {graph_field} ← {col}")
            else:
                logger.info(f"  {graph_field} ← {df_col}")

    # Normalize chart type - handle multiple formats
    chart_type_normalized = chart_type
    
    # Strip enum prefix if present (e.g., "ChartType.BUBBLE_CHART" -> "BUBBLE_CHART")
    if '.' in chart_type:
        chart_type = chart_type.split('.')[-1]
    
    # Replace underscores with spaces and title case
    chart_type_cleaned = chart_type.replace('_', ' ').title()
    
    # Map common variations to standard names
    chart_type_mapping = {
        "Pie Chart": "Pie Chart",
        "Pie": "Pie Chart",
        "Bar Chart": "Bar Chart",
        "Bar": "Bar Chart",
        "Column Chart": "Column Chart",
        "Column": "Column Chart",
        "Line Chart": "Line Chart",
        "Line": "Line Chart",
        "Stacked Bar Chart": "Stacked Bar Chart",
        "Stacked Bar": "Stacked Bar Chart",
        "Bubble Chart": "Bubble Chart",
        "Bubble": "Bubble Chart",
        "Scatter Chart": "Scatter Chart",
        "Scatter": "Scatter Chart",
        "Geo Chart": "Geo Chart",
        "Geo": "Geo Chart",
    }
    
    # Try to find a match in the mapping
    if chart_type_cleaned in chart_type_mapping:
        chart_type_normalized = chart_type_mapping[chart_type_cleaned]
    else:
        # Try exact match with original
        if chart_type in ASSEMBLERS:
            chart_type_normalized = chart_type
        else:
            # Last resort: try the cleaned version directly
            chart_type_normalized = chart_type_cleaned
    
    if verbose:
        logger.info(f"Chart Type (normalized): {chart_type_normalized}")
    
    assembler = ASSEMBLERS.get(chart_type_normalized)
    
    if not assembler:
        available_types = ", ".join(ASSEMBLERS.keys())
        raise ValueError(
            f"No assembler found for chart type: '{chart_type}' "
            f"(normalized to: '{chart_type_normalized}'). "
            f"Available types: {available_types}"
        )

    # Assemble the data
    graph_data = assembler(df, mappings_dict, metadata_config)

    if verbose:
        logger.info("GRAPH DATA ASSEMBLED")
        logger.info(f"   Data items: {len(graph_data.get('data', []))}")
        logger.info(f"   Title: {graph_data['metadata']['title']}")
        logger.info("=" * 80)

    return graph_data