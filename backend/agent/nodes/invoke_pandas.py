from typing import Any, Dict
from agent.state import AgentState
import tempfile
import csv
from pandas_agent.graph import pandas_agent_graph
from agent.utils.usage_tracking import get_usage_tracker
from agent.utils.node_metrics import record_node_seconds
from agent.utils.model_config_loader import load_model_config
from langchain_core.messages import HumanMessage
from otel_tracing import track_time
import os
import json
from logger import logger
from langchain_core.runnables import RunnableConfig
@track_time("Node: Invoke Pandas")
async def invoke_pandas_agent_node(state: AgentState) -> AgentState:
    """
    Invokes the Pandas Agent to perform complex aggregations on the SQL results.
    """
    logger.info("🐼 Invoking Pandas Agent Node")
    
    db_results = state.get("db_result") or []
    db_columns = state.get("db_columns") or []
    query = state.get("query", "")
    
    if not db_results:
        logger.warning("No DB results to process with Pandas Agent")
        return state

    # Helper to make data JSON serializable (reused from graph_agent_bridge)
    def _to_jsonable(value):
        import datetime
        if hasattr(value, "model_dump"):
            value = value.model_dump()
        if isinstance(value, (int, float, str, type(None))):
            return value
        if isinstance(value, bytes):
            try:
                return value.decode("utf-8")
            except Exception:
                return value.hex()
        if isinstance(value, (tuple, set, list)):
            return [_to_jsonable(v) for v in list(value)]
        if isinstance(value, dict):
            return {k: _to_jsonable(v) for k, v in value.items()}
        if isinstance(value, (datetime.datetime, datetime.date)):
            return value.isoformat()
        return str(value)

    # Convert db_results to rows and header
    if isinstance(db_results, (list, tuple)) and db_results and all(isinstance(r, dict) for r in db_results):
        header = list({k for d in db_results for k in d.keys()})
        rows = [[_to_jsonable(r.get(col)) for col in header] for r in db_results]
    elif isinstance(db_results, (list, tuple)) and db_results and all(isinstance(r, (list, tuple)) for r in db_results):
        if db_columns:
            header = [str(c) for c in db_columns]
        else:
            header = [f"col_{i}" for i in range(len(db_results[0]))]
        rows = [[_to_jsonable(v) for v in r] for r in db_results]
    elif isinstance(db_results, str):
        header, rows = ["value"], [[db_results]]
    else:
        header, rows = ["value"], [[_to_jsonable(db_results)]]

    # Create temporary CSV
    try:
        with tempfile.NamedTemporaryFile(delete=False, mode="w", newline='', suffix=".csv") as tf:
            writer = csv.writer(tf)
            writer.writerow(header)
            writer.writerows(rows)
            csv_path = tf.name
        
        logger.info(f"Created temp CSV at {csv_path} with {len(rows)} rows")

        # Prepare input for Pandas Agent
        pandas_input = {
            "messages": [HumanMessage(content=query)],
            "csv_path": csv_path,
            "query": query,
            "chart_type": None,
            "plan": None,
            "execution_result": None,
            "error": None,
            "retry_count": 0,  # Initialize retry counter
            # Pass owner context so Pandas agent can use owner-specific credentials
            "owner_id": state.get("owner_id"),
            "agent_id": state.get("agent_id"),  # Pass agent_id for agent-specific config
        }

        # Invoke Pandas Agent (async)
        logger.info("Running Pandas Agent Graph...")
        import time
        start_time = time.time()
        config = RunnableConfig(
            tags=["pandas_agent"],
            metadata={"owner_id": state.get("owner_id"), "agent_id": state.get("agent_id")}
        )
        result = await pandas_agent_graph.ainvoke(pandas_input, config=config)
        execution_time = time.time() - start_time
        
        execution_result = result.get("execution_result")
        plan = result.get("plan")
        error = result.get("error")

        if error:
            logger.error(f"Pandas Agent Error: {error}")
            state["pandas_execution_result"] = f"Pandas Agent failed: {error}"
        else:
            logger.info("Pandas Agent Success")
            state["pandas_execution_result"] = execution_result
            # Convert plan to dict if it's a pydantic model
            if hasattr(plan, "model_dump"):
                state["pandas_plan"] = plan.model_dump()
            else:
                state["pandas_plan"] = plan

        try:
            token_metrics = result.get("token_metrics") or {}
            input_tokens = int(token_metrics.get("input_tokens", 0))
            output_tokens = int(token_metrics.get("output_tokens", 0))
            total_tokens = int(token_metrics.get("total_tokens", 0))

            try:
                cfg = load_model_config()
            except Exception as e:
                logger.warning(f"Could not load model_config.json for pandas agent usage tracking: {e}")
                cfg = {}

            pandas_conf = cfg.get("pandas_agent", {}).get("default", {})
            pandas_provider = pandas_conf.get("provider")
            pandas_model = pandas_conf.get("model") or os.getenv("PANDAS_MODEL")
            pandas_temperature = pandas_conf.get("temperature", 0.0)

            # Determine key_type based on credential source. Resolved before the metric
            # record below so both the health event and the usage event report the same
            # credential owner for this node.
            try:
                from agent.utils.owner_credential_utils import get_owner_api_key_for_provider, get_provider_from_model
                prov_for_key = pandas_provider or get_provider_from_model(pandas_model or "")
                _, key_type = await get_owner_api_key_for_provider(state.get("owner_id"), prov_for_key, return_source=True)
                key_type = key_type or "platform-key"
            except Exception:
                key_type = "platform-key"

            # Same numbers, kept locally for the health event's per-node breakdown.
            record_node_seconds(
                state, "invoke_pandas", execution_time,
                provider=pandas_provider, model=pandas_model,
                input_tokens=input_tokens, output_tokens=output_tokens,
                total_tokens=total_tokens, key_type=key_type, errors=1 if error else 0,
            )

            tracker = get_usage_tracker()
            metadata = {
                "model": pandas_model,
                "provider": pandas_provider,
                "temperature": pandas_temperature,
            }
            usage_payload = {
                "owner_id": state.get("owner_id"),
                "service_id": state.get("agent_id"),
                "service_type": os.getenv("USAGE_SERVICE_TYPE", "nl2sql"),
                "operation": "llm_call",
                "label": "pandas_agent",
                "session_id": state.get("session_id"),
                "request_id": state.get("request_id"),
                "key_type": key_type,
                "metadata": metadata,
                "metrics": [
                    {"name": "input_tokens", "value": float(input_tokens or 0)},
                    {"name": "output_tokens", "value": float(output_tokens or 0)},
                    {"name": "total_tokens", "value": float(total_tokens or 0)},
                    {"name": "duration_ms", "value": float(execution_time * 1000.0)},
                ],
            }
            logger.info(f"Usage (local) pandas_agent payload={json.dumps(usage_payload)}")
            await tracker.record_event(
                owner_id=state.get("owner_id"),
                agent_id=state.get("agent_id"),
                operation="llm_call",
                label="pandas_agent",
                session_id=state.get("session_id"),
                request_id=state.get("request_id"),
                key_type=key_type,
                metadata=metadata,
                metrics=[
                    {"name": "input_tokens", "value": float(input_tokens or 0)},
                    {"name": "output_tokens", "value": float(output_tokens or 0)},
                    {"name": "total_tokens", "value": float(total_tokens or 0)},
                    {"name": "duration_ms", "value": float(execution_time * 1000.0)},
                ],
            )
            try:
                rows_processed = 0
                if not error and isinstance(execution_result, str) and execution_result:
                    if "CSV_DATA_START" in execution_result and "CSV_DATA_END" in execution_result:
                        start = execution_result.index("CSV_DATA_START") + len("CSV_DATA_START")
                        end = execution_result.index("CSV_DATA_END", start)
                        csv_text = execution_result[start:end].strip()
                        non_empty_lines = [ln for ln in csv_text.splitlines() if ln.strip() != ""]
                        rows_processed = max(0, len(non_empty_lines) - 1)
                    else:
                        import re
                        m = re.search(r"Shape:\s*(\d+)\s*rows\s*×\s*(\d+)\s*columns", execution_result)
                        if m:
                            rows_processed = int(m.group(1))
                code_payload = {
                    "owner_id": state.get("owner_id"),
                    "service_id": state.get("agent_id"),
                    "service_type": os.getenv("USAGE_SERVICE_TYPE", "nl2sql"),
                    "operation": "code_execution",
                    "label": "pandas_execution",
                    "session_id": state.get("session_id"),
                    "request_id": state.get("request_id"),
                    "metadata": {"success": not bool(error)},
                    "metrics": [
                        {"name": "duration_ms", "value": float(execution_time * 1000.0)},
                        {"name": "rows_processed", "value": float(rows_processed)},
                    ],
                }
                logger.info(f"Usage (local) pandas_agent code payload={json.dumps(code_payload)}")
                await tracker.record_event(
                    owner_id=state.get("owner_id"),
                    agent_id=state.get("agent_id"),
                    operation="code_execution",
                    label="pandas_execution",
                    session_id=state.get("session_id"),
                    request_id=state.get("request_id"),
                    key_type=None,
                    metadata={"success": not bool(error)},
                    metrics=[
                        {"name": "duration_ms", "value": float(execution_time * 1000.0)},
                        {"name": "rows_processed", "value": float(rows_processed)},
                    ],
                    operation_id="invoke_pandas_agent",
                )
            except Exception as e2:
                logger.warning(f"Failed to record pandas_agent code event (non-blocking): {e2}")
        except Exception as e:
            logger.warning(f"Failed to record pandas_agent usage event (non-blocking): {e}")

    except Exception as e:
        logger.error(f"Error in invoke_pandas_agent_node: {e}")
        state["pandas_execution_result"] = f"Error invoking Pandas Agent: {str(e)}"
    finally:
        # Cleanup CSV
        if 'csv_path' in locals() and os.path.exists(csv_path):
            try:
                os.remove(csv_path)
                logger.info(f"Removed temp CSV {csv_path}")
            except Exception as e:
                logger.warning(f"Failed to remove temp CSV: {e}")

    return state
