"""
Graph API using the LangGraph Graph Agent.
Accepts a CSV file + natural language question → returns structured chart data.
Supports both graph generation and direct conversational responses.
"""

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
import tempfile
import os
from typing import Optional, List, Union
from pydantic import BaseModel
from datetime import datetime
from dotenv import load_dotenv

from chart_agent.utils.tracing import trace
from chart_agent.models.graph_pydantic_models import ChartType, GraphData, GraphResponse
from chart_agent.graph import generate_graph_from_csv
from logger import logger
from chart_agent.models.graph_pydantic_models import DirectResponse, GraphGenerationResponse
from agent.utils.usage_tracking import get_usage_tracker
from otel_tracing import track_time

# load_dotenv()

router = APIRouter(prefix="/v1")

# Union type for API response
UnifiedResponse = Union[DirectResponse, GraphGenerationResponse]


@router.post("/chart_agent/generate")
@track_time("API: Chart Agent - Generate Graph")
async def generate_graph(
    query: str = Form(..., description="Natural language request for a chart, e.g. 'Show top 10 products by sales as a bar chart', or conversational queries like 'Hi'"),
    allowed_graphs: Optional[str] = Form(None, description='Optional comma-separated list of allowed chart types.'),
    owner_id: Optional[str] = Form(None, description="Owner identifier for usage tracking and multi-tenant routing"),
    file: UploadFile = File(..., description="CSV file to analyze")
) -> UnifiedResponse:
    """
    Generate a chart from CSV using the LangGraph Graph Agent OR handle direct conversational queries.
    
    Returns:
        - DirectResponse: For greetings and general questions
        - GraphGenerationResponse: For data visualization requests with structured chart data
    """
    logger.info(f"Graph generation request received - File: {file.filename}, Query: {query[:100]}, Allowed graphs: {allowed_graphs}")
    
    # Validate file type
    if not file.filename.lower().endswith('.csv'):
        logger.error(f"Invalid file type attempted: {file.filename}")
        raise HTTPException(status_code=400, detail="Only CSV files are supported")

    # Parse allowed_graphs if provided
    parsed_allowed_graphs: Optional[List[ChartType]] = None
    if allowed_graphs:
        try:
            names = [name.strip().lower() for name in allowed_graphs.split(",")]
            logger.info(f"Parsing allowed graph types: {names}")
            parsed_allowed_graphs = []
            for name in names:
                # Map string → ChartType enum
                for ct in ChartType:
                    if ct.value.lower() == name:
                        parsed_allowed_graphs.append(ct)
                        break
                else:
                    raise ValueError(f"Unknown chart type: {name}")
            logger.info(f"Parsed {len(parsed_allowed_graphs)} allowed chart types")
        except Exception as e:
            logger.error(f"Invalid allowed_graphs format: {str(e)}")
            raise HTTPException(status_code=400, detail=f"Invalid allowed_graphs format: {str(e)}")

    # Save uploaded file temporarily
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as temp_file:
        content = await file.read()
        temp_file.write(content)
        temp_file_path = temp_file.name
    logger.info(f"CSV file saved temporarily at: {temp_file_path}")

    try:
        import time
        start_time = time.time()
        with trace(name="GraphAgentGenerate", project_name=os.getenv("LANGCHAIN_PROJECT")):
            logger.info(f"Starting graph agent generation for query: {query[:100]}")
            
            # Call the LangGraph-powered graph agent
            result = await generate_graph_from_csv(
                csv_path=temp_file_path,
                question=query,
                allowed_graphs=parsed_allowed_graphs,
                owner_id=owner_id
            )
            execution_time = time.time() - start_time
            
            # Check if it's a direct response (dict with is_direct_response flag)
            if isinstance(result, dict) and result.get("is_direct_response"):
                logger.info("Direct conversational response provided")
                try:
                    tracker = get_usage_tracker()
                    await tracker.record_event(
                        owner_id=owner_id,
                        agent_id=None,
                        operation="chart_api_request",
                        label="chart_api_request_llm",
                        session_id=None,
                        request_id=None,
                        operation_id="chart_api",
                        service_type="nl2sql",
                        metadata={"endpoint": "chart_agent/generate", "is_direct_response": True},
                        metrics=[
                            {"name": "execution_time_seconds", "value": execution_time},
                        ],
                    )
                except Exception:
                    pass
                return DirectResponse(
                    message=result["response"],
                    reasoning=result.get("reasoning"),
                    graph_generated=False
                )
            
            # It's a GraphResponse object - graph was generated
            logger.info(f"Graph generation completed. Chart type: {result.graph_suggestion}")
            try:
                tracker = get_usage_tracker()
                extra_metrics = []
                try:
                    df = result.dataframe.model_dump() if result.dataframe else None
                    if df:
                        rows = len(df.get("data", []))
                        cols = len(df.get("columns", []))
                        extra_metrics.append({"name": "rows_returned", "value": float(rows)})
                        extra_metrics.append({"name": "columns_count", "value": float(cols)})
                except Exception:
                    pass
                # Extract token metrics if available
                token_metrics = getattr(result, "token_metrics", {})
                input_tokens = token_metrics.get("input_tokens")
                output_tokens = token_metrics.get("output_tokens")
                total_tokens = token_metrics.get("total_tokens")
                # Add step-level metrics to extra_metrics
                for k, v in token_metrics.items():
                    if k not in ["input_tokens", "output_tokens", "total_tokens"]:
                        extra_metrics.append({"name": k, "value": float(v)})

                await tracker.record_graph_generation(
                    owner_id=owner_id,
                    agent_id=None,
                    execution_time=execution_time,
                    chart_type=str(result.graph_suggestion) if result.graph_suggestion else None,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                    extra_metrics=extra_metrics,
                    session_id=None,
                    request_id=None,
                    operation_id="chart_api",
                    metadata=None,
                    # service type tracking for chart API usage
                    # using record_event inside record_graph_generation
                    # not needed since record_graph_generation constructs event
                )
            except Exception:
                pass
            
            return GraphGenerationResponse(
                chart_suggestion=result.graph_suggestion,
                chart_data=result.graph_data,
                dataframe=result.dataframe.model_dump() if result.dataframe else None,
                chart_generated=True
            )

    except Exception as e:
        logger.error(f"Error generating graph: {str(e)}", exc_info=True)
        try:
            tracker = get_usage_tracker()
            await tracker.record_event(
                owner_id=owner_id,
                agent_id=None,
                operation="chart_api_request",
                label="chart_api_request",
                session_id=None,
                request_id=None,
                operation_id="chart_api",
                service_type="chart_agent",
                metadata={"endpoint": "chart_agent/generate", "error": str(e)},
                metrics=[
                    {"name": "execution_time_seconds", "value": 0.0},
                ],
            )
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"Error generating graph: {str(e)}")

    finally:
        # Clean up temp file
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
            logger.debug(f"Temporary CSV file cleaned up: {temp_file_path}")
