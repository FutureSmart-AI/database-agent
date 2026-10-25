from pydantic import BaseModel, Field
from typing import Optional, Union, List, Dict, Any

#  --- Reusable Sub-Models ---
class ChartAxis(BaseModel):
    """Defines the properties of a chart axis."""
    label: str = Field(description="The label text for the axis.")
    field: Optional[str] = Field(None, description="The data field corresponding to this axis.")
    format: Optional[str] = Field(None, description="The format for the axis values (e.g., 'currency', 'percentage').")
    rotation: Optional[int] = Field(None, description="The rotation angle for axis labels.")

class ChartLegend(BaseModel):
    """Defines the properties of a chart legend."""
    show: bool = Field(description="Whether to display the legend.")
    position: Optional[str] = Field(None, description="Position of the legend (e.g., 'top', 'right', 'bottom').")
    title: Optional[str] = Field(None, description="An optional title for the legend.")

class ChartTooltip(BaseModel):
    """Defines the properties of a chart tooltip."""
    show: bool = Field(description="Whether to display the tooltip on hover.")
    format: Optional[str] = Field(None, description="A format string for the tooltip content. Use {key} for placeholders.")

# --- Bar & Column Chart Models ---
class BarColumnDataItem(BaseModel):
    """A single data item for a Bar or Column Chart."""
    category: str = Field(..., description="The label for the category on the main axis.")
    value: Union[int, float] = Field(..., description="The numerical value for this category.")

class BarColumnChartMetadata(BaseModel):
    """Metadata for a Bar or Column Chart."""
    title: str = Field(..., description="The main title of the chart.")
    x_axis: ChartAxis
    y_axis: ChartAxis
    legend: ChartLegend
    colors: List[str] = Field(..., description="A list of hex color codes for the bars/columns.")

class BarColumnChartData(BaseModel):
    """The complete structured output for a Bar or Column Chart."""
    data: List[BarColumnDataItem]
    metadata: BarColumnChartMetadata

# --- Pie Chart Models ---
class PieChartDataItem(BaseModel):
    """A single data item (slice) for a Pie Chart."""
    label: str = Field(..., description="The name/label of the pie slice.")
    value: Union[int, float] = Field(..., description="The numerical value of the pie slice.")

class PieChartMetadata(BaseModel):
    """Metadata for a Pie Chart."""
    title: str = Field(..., description="The main title of the chart.")
    legend: ChartLegend
    colors: List[str] = Field(..., description="A list of hex color codes for the slices.")
    show_percentages: Optional[bool] = Field(None, description="Whether to display percentages on slices.")
    total_label: Optional[str] = Field(None, description="A label for the total value, if displayed.")

class PieChartData(BaseModel):
    """The complete structured output for a Pie Chart."""
    data: List[PieChartDataItem]
    metadata: PieChartMetadata

# --- Line Chart Models ---
class LineChartDataItem(BaseModel):
    """A single data point for a Line Chart."""
    x: Union[str, int, float] = Field(..., description="The value for the x-axis (e.g., date, time, category).")
    y: Union[int, float] = Field(..., description="The numerical value for the y-axis.")

class LineProperties(BaseModel):
    """Defines the visual properties of the line in a Line Chart."""
    color: Optional[str] = Field(None, description="Hex color code for the line.")
    width: Optional[int] = Field(None, description="The width of the line in pixels.")
    smooth: Optional[bool] = Field(None, description="Whether to render the line with smooth curves.")

class LineChartMetadata(BaseModel):
    """Metadata for a Line Chart."""
    title: str = Field(..., description="The main title of the chart.")
    x_axis: ChartAxis
    y_axis: ChartAxis
    line: Optional[LineProperties] = None
    legend: ChartLegend

class LineChartData(BaseModel):
    """The complete structured output for a Line Chart."""
    data: List[LineChartDataItem]
    metadata: LineChartMetadata

# --- Stacked Bar Chart Models ---
class StackedBarColumnSegment(BaseModel):
    """Represents a single segment within a stacked bar (e.g., a specific tenant or a vacant area)."""
    category: str = Field(..., description="The name of the segment category. This should be the Tenant's Name or 'Vacant'.")
    value: Union[int, float] = Field(..., description="The numerical value of this segment (e.g., square footage).")
    details: Optional[Dict[str, Union[str, int, float, None]]] = Field(None, description="A flexible key-value store for additional details, used for tooltips. Keys should be human-readable labels.")

class StackedBarDataItem(BaseModel):
    """Represents a single complete bar in the chart (e.g., one floor)."""
    index: str = Field(..., description="The label for the main axis for this bar (e.g., 'Beacon Plaza 15 - 1').")
    segments: List[StackedBarColumnSegment] = Field(..., description="A list of all segments that make up this bar.")

class StackedBarChartMetadata(BaseModel):
    """Metadata for a Stacked Bar Chart."""
    title: str = Field(..., description="The main title of the chart.")
    x_axis: ChartAxis
    y_axis: ChartAxis
    legend: ChartLegend
    colors: Dict[str, str] = Field(..., description="A dictionary mapping segment category names (e.g., Tenant Names, 'Vacant') to their hex color codes. Keys MUST match the 'category' fields in the segments.")
    stack_type: Optional[str] = Field('normal', description="The type of stacking, e.g., 'normal' or 'percent'.")
    chart_orientation: str = Field('horizontal', description="The orientation of the chart, either 'horizontal' or 'vertical'.")

class StackedBarChartData(BaseModel):
    """The complete structured output for a detailed, interactive Stacked Bar Chart."""
    data: List[StackedBarDataItem]
    metadata: StackedBarChartMetadata

# --- Bubble Chart Models ---
class BubbleChartDataItem(BaseModel):
    """A single data point for a Bubble Chart."""
    x: Union[int, float] = Field(..., description="The numerical value for the x-axis.")
    y: Union[int, float] = Field(..., description="The numerical value for the y-axis.")
    size: Union[int, float] = Field(..., description="The numerical value determining the bubble's size.")
    label: str = Field(..., description="The label for the bubble, often shown in tooltips or legends.")

class SizeAxis(BaseModel):
    """Defines the properties of the size-determining axis in a Bubble Chart."""
    label: str = Field(..., description="The label for the size metric (e.g., 'Avg. Satisfaction Score').")
    min_size: Optional[int] = Field(None, description="The minimum pixel size for a bubble.")
    max_size: Optional[int] = Field(None, description="The maximum pixel size for a bubble.")

class BubbleChartMetadata(BaseModel):
    """Metadata for a Bubble Chart."""
    title: str = Field(..., description="The main title of the chart.")
    x_axis: ChartAxis
    y_axis: ChartAxis
    size_axis: SizeAxis
    colors: List[str] = Field(..., description="A list of hex color codes for the bubbles.")
    legend: ChartLegend

class BubbleChartData(BaseModel):
    """The complete structured output for a Bubble Chart."""
    data: List[BubbleChartDataItem]
    metadata: BubbleChartMetadata

# --- Geo Chart Models ---
class ColorAxis(BaseModel):
    """Defines the color gradient for a Geo Chart."""
    min_value: Optional[int] = Field(None, description="The minimum value for the color scale.")
    colors: List[str] = Field(..., description="A list of hex color codes defining the gradient (e.g., from light to dark).")

class GeoChartMetadata(BaseModel):
    """Metadata for a Geo Chart."""
    title: str = Field(..., description="The main title of the chart.")
    region: str = Field('world', description="The geographic region to display (e.g., 'world', 'USA', 'europe').")
    color_axis: ColorAxis
    legend: ChartLegend
    tooltip: ChartTooltip

class GeoChartData(BaseModel):
    """The complete structured output for a Geo Chart."""
    data: List[List[Union[str, int, float]]] = Field(..., description="A list of lists. The first inner list MUST be the header row (e.g., ['State', 'Value', 'Country']). Subsequent lists are the data rows. A column named 'Country' containing a 3-letter ISO code is MANDATORY.")
    metadata: GeoChartMetadata

# --- Scatter Chart Models ---
class ScatterChartDataPayload(BaseModel):
    """The data payload for a Scatter Chart."""
    x: List[Union[int, float]] = Field(..., description="A list of numerical values for the x-axis.")
    y: List[Union[int, float]] = Field(..., description="A list of numerical values for the y-axis.")

class PointProperties(BaseModel):
    """Defines the visual properties of points in a Scatter Chart."""
    color: Optional[str] = Field(None, description="Hex color code for the points.")
    size: Optional[int] = Field(None, description="The size of the points in pixels.")

class TrendLine(BaseModel):
    """Defines the properties of the trend line in a Scatter Chart."""
    show: bool = Field(..., description="Whether to display a trend line.")
    color: Optional[str] = Field(None, description="Hex color code for the trend line.")

class ScatterChartMetadata(BaseModel):
    """Metadata for a Scatter Chart."""
    title: str = Field(..., description="The main title of the chart.")
    x_axis: ChartAxis
    y_axis: ChartAxis
    point: Optional[PointProperties] = None
    trend_line: Optional[TrendLine] = None
    legend: ChartLegend

class ScatterChartData(BaseModel):
    """The complete structured output for a Scatter Chart."""
    data: ScatterChartDataPayload
    metadata: ScatterChartMetadata
