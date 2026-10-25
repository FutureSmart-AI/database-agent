"""
Updated CSV API using LangGraph CSV agent.
"""

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
import tempfile
import os
from typing import Optional
from pydantic import BaseModel
from datetime import datetime
from dotenv import load_dotenv
from csv_agent.utils.tracing import traceable, trace
from csv_agent.graph import process_csv_query
from csv_agent.models.pydantic_models import CSVQueryResponse,CSVQueryRequest
from logger import logger
from agent.utils.usage_tracking import get_usage_tracker
from otel_tracing import track_time

# load_dotenv()

router = APIRouter(prefix="/v1")




@router.post("/csv_agent/api/chat", response_model=CSVQueryResponse)
@track_time("API: CSV Agent - Chat")
async def csv_query(
    query: str = Form(..., description="Natural language query about the CSV data"),
    answer: Optional[bool] = Form(False, description="Whether to generate a natural language answer"),
    owner_id: Optional[str] = Form(None, description="Owner identifier for usage tracking and multi-tenant routing"),
    file: UploadFile = File(..., description="CSV file to analyze")
):
    """
    Process CSV file with natural language query using LangGraph CSV agent.
    Optionally includes a natural language answer based on the processed data.
    """
    logger.info(f"CSV query request received - File: {file.filename}, Query: {query[:100]}, Generate Answer: {answer}")

    # The owner's rolling-24h query cap, shared with agent chat: a CSV question and an
    # agent question draw on the same allowance.
    #
    # ONLY ENFORCEABLE WHEN owner_id IS SENT. This endpoint has no auth dependency and
    # owner_id is an optional caller-supplied form field, so omitting it skips the cap.
    # That is a pre-existing gap in this endpoint, not one the cap introduces — closing it
    # means giving this route the same auth as agent chat, which is a separate change.
    from api.v1.routers.chat import enforce_query_cap
    await enforce_query_cap((owner_id or "").strip().lower() or None, surface="csv_agent")
    
    # Validate file type
    if not file.filename.endswith('.csv'):
        logger.error(f"Invalid file type attempted: {file.filename}")
        raise HTTPException(status_code=400, detail="Only CSV files are supported")
    
    # Save the uploaded file to a temporary directory
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as temp_file:
        content = await file.read()
        temp_file.write(content)
        temp_file_path = temp_file.name
    logger.info(f"CSV file saved temporarily at: {temp_file_path}")
    
    try:
        import time
        start_time = time.time()
        # Wrap entire CSV query processing in a trace
        with trace(name="CSVQuery", project_name=os.getenv("LANGCHAIN_PROJECT")):
            logger.info(f"Starting CSV agent processing for query: {query[:100]}")
            # Process CSV with LangGraph CSV agent
            result = await process_csv_query(
                csv_path=temp_file_path,
                query=query,
                generate_answer=answer,
                owner_id=owner_id
            )
            execution_time = time.time() - start_time
            logger.info(f"CSV agent processing completed. Result rows: {len(result['dataframe'].get('data', []))}")
            
            try:
                tracker = get_usage_tracker()
                rows = len(result["dataframe"].get("data", [])) if result.get("dataframe") else 0
                cols = len(result["dataframe"].get("columns", [])) if result.get("dataframe") else 0
                await tracker.record_event(
                    owner_id=owner_id,
                    agent_id=None,
                    operation="csv_api_request",
                    label="csv_api_request",
                    session_id=None,
                    request_id=None,
                    operation_id="csv_api",
                    service_type="csv_agent",
                    metadata={"endpoint": "csv_agent/api/chat", "generate_answer": bool(answer)},
                    metrics=[
                        {"name": "execution_time_seconds", "value": execution_time},
                        {"name": "rows_returned", "value": float(rows)},
                        {"name": "columns_count", "value": float(cols)},
                    ],
                )
            except Exception:
                pass
            return CSVQueryResponse(
                dataframe=result["dataframe"],
                answer=result.get("answer")
            )
        
    except Exception as e:
        logger.error(f"Error processing CSV query: {str(e)}", exc_info=True)
        try:
            tracker = get_usage_tracker()
            # Extract token metrics if available
            token_metrics = getattr(result, "token_metrics", {})
            input_tokens = token_metrics.get("input_tokens")
            output_tokens = token_metrics.get("output_tokens")
            total_tokens = token_metrics.get("total_tokens")
            metrics = [
                    {"name": "execution_time_seconds", "value": 0.0},
                ]
            if input_tokens is not None:
                    metrics.append({"name": "input_tokens", "value": float(input_tokens)})
            if output_tokens is not None:
                    metrics.append({"name": "output_tokens", "value": float(output_tokens)})
            if total_tokens is not None:
                    metrics.append({"name": "total_tokens", "value": float(total_tokens)})
            await tracker.record_event(
                    owner_id=owner_id,
                    agent_id=None,
                    operation="csv_api_request",
                    label="csv_api_request_llm",
                    session_id=None,
                    request_id=None,
                    operation_id="csv_api",
                    service_type="nl2sql",
                    metadata={"endpoint": "csv_agent/api/chat", "error": str(e)},
                    metrics=metrics,
                )
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"Error processing CSV: {str(e)}")
    
    finally:
        # Clean up the temporary file
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
            logger.debug(f"Temporary CSV file cleaned up: {temp_file_path}")
