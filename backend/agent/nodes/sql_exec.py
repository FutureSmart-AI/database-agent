import os
import json
import time
from typing import Any, Optional, Tuple, List


from langsmith import traceable
from agent.state import AgentState
from langsmith import traceable
import agent.db_utils.table_description_db_utils as table_description_db_utils
from logger import logger
from agent.utils.usage_tracking import get_usage_tracker
from agent.utils.node_metrics import record_node_seconds
from otel_tracing import track_time
import agent.db_utils.table_description_db_utils as table_description_db_utils


def try_exec_sql(db_details: dict, sql: str) -> Tuple[bool, List[tuple] | None, Optional[str]]:
    """Execute SQL against a live DB connection using existing sync utilities.

    db_details is expected to be the object returned at api level under key 'db_details'.
    """
    try:
        connection = table_description_db_utils.get_db_connection({"db_details": db_details})
        with connection.cursor() as cursor:
            cursor.execute(sql)
            rows = cursor.fetchall()
            # Capture column names when available
            columns = [desc[0] for desc in (cursor.description or [])]
        connection.commit()
        connection.close()
        # Attach columns to rows via second return path is not possible here; handled in caller
        return True, (columns, rows), None
    except Exception as e:  # noqa: BLE001
        logger.error(f"SQL exec error: {e}")
        try:
            connection.close()
        except Exception:
            pass
        return False, None, str(e)


@traceable(run_type="tool", name="node_sql_exec")
@track_time("Node: SQL Execution")
async def node_sql_exec(state: AgentState) -> AgentState:
    logger.info(
        "[WF] step.start=sql_exec | request_id=%s | session_id=%s",
        state.get("request_id"),
        state.get("session_id"),
    )
    # Expect upstream to inject real db details at runtime via state['runtime_db_details']
    db_details = state.get("runtime_db_details")  # type: ignore[assignment]
    ok, rows, err = (False, None, "No SQL")

    if state.get("answerability_error"):
        state.update(sql_query="", sql_error=None, db_result=[], db_columns=None)
        return state

    # sql_gen may already have denied before schema sampling. The graph still
    # enters this node; an empty denied query is terminal, not a retryable "No SQL".
    if state.get("access_policy_error") or state.get("access_denied_tables"):
        from agent.utils.table_access import deny_table_access
        return deny_table_access(state, tables=state.get("access_denied_tables"),
                                 policy_error=state.get("access_policy_error", False))
    
    if not state.get("sql_query"):
        logger.warning("node_sql_exec: No SQL query provided in state")
        state["sql_error"] = state.get("sql_error") or "No SQL query to execute"
        state["db_result"] = []
        return state
        
    if not db_details:
        logger.warning("node_sql_exec: No database details provided in state")
        state["sql_error"] = "No database connection details"
        state["db_result"] = []
        return state
    
    # Table visibility is enforced HERE, before the query reaches the database — not by
    # asking final_answer to refuse afterwards (agent/utils/prompts.py), which let the
    # query run and returned its rows and SQL underneath the refusal, and never caught an
    # excluded table reached through a join. Both entry points to this node — the single-DB
    # graph and each cross-DB fan-out branch — go through this check.
    from agent.utils.table_access import get_table_visibility, blocked_tables, deny_table_access
    blocked = None
    try:
        permitted, excluded = await get_table_visibility(
            state.get("user_id"),
            state.get("agent_id"),
            db_details.get("db_id") or state.get("db_id"),
        )
        blocked = blocked_tables(
            state["sql_query"], permitted, excluded, db_details.get("db_engine")
        )
    except Exception as e:  # noqa: BLE001
        logger.error("node_sql_exec: table access policy could not be verified (%s)", type(e).__name__)
        return deny_table_access(state, policy_error=True)

    if blocked:
        # Log the query server-side for audit, then drop it from state. Everything
        # downstream — the final_answer prompt, debug_info's sql_query/db_result, the
        # CSV export, the chart agent — reads these keys, so clearing them here is what
        # keeps the excluded table's SQL and rows out of the response entirely.
        logger.warning(
            "[WF] sql_exec BLOCKED: query reads excluded table(s) %s | agent_id=%s | "
            "request_id=%s | sql=%s",
            blocked, state.get("agent_id"), state.get("request_id"), state["sql_query"],
        )
        deny_table_access(state, tables=blocked)
        # Not a sql_error: that would send the graph back to sql_gen to retry, and a
        # retry cannot help — the model was never offered the excluded table, so it
        # would spend another LLM call arriving at the same place. Empty db_result
        # routes straight to final_answer via check_pandas_needed.
        record_node_seconds(state, "sql_exec", 0.0, extra={"access_denied": len(blocked)})
        return state

    state["access_denied_tables"] = []
    state["access_policy_error"] = False

    logger.info(f"node_sql_exec: Executing SQL: {state['sql_query'][:100]}...")
    start_time = time.time()
    # Run the blocking DB I/O in a worker thread so it never stalls the event loop — this is
    # what lets cross-DB fan-out branches execute their SQL truly SIMULTANEOUSLY (and keeps
    # unrelated concurrent requests responsive on single-DB queries too).
    import asyncio as _asyncio
    ok, result, err = await _asyncio.to_thread(try_exec_sql, db_details, state["sql_query"])  # type: ignore[arg-type]
    execution_time = time.time() - start_time
    
    if ok:
        columns, rows = result if isinstance(result, tuple) else ([], result)
        rows_count = len(rows) if rows else 0
        logger.info(f"node_sql_exec: SQL executed successfully, returned {rows_count} rows")
        state["db_result"] = rows if rows else []
        state["db_columns"] = columns if columns else None
        state["sql_error"] = None

        # Health event: sql_exec spends no tokens, but its time is time inside the
        # customer's database — the one latency component we don't control.
        record_node_seconds(state, "sql_exec", execution_time, extra={"rows_returned": rows_count})
        state["sql_exec_ms"] = state.get("sql_exec_ms", 0) + int(execution_time * 1000)


        # Record usage event (non-blocking)
        try:
            tracker = get_usage_tracker()
            usage_payload = {
                "owner_id": state.get("owner_id"),
                "service_id": state.get("agent_id"),
                "service_type": os.getenv("USAGE_SERVICE_TYPE", "nl2sql"),
                "operation": "db_query",
                "label": "nl2sql_db_execution",
                "session_id": state.get("session_id"),
                "request_id": state.get("request_id"),
                "operation_id": "sql_exec",
                "metadata": {"sql_query": state.get("sql_query"), "success": True},
                "metrics": [
                    {"name": "duration_ms", "value": float(execution_time * 1000.0)},
                    {"name": "rows_returned", "value": float(rows_count)},
                ],
            }
            logger.info(f"Usage (local) sql_exec success payload={json.dumps(usage_payload)}")
            await tracker.record_event(
                owner_id=state.get("owner_id"),
                agent_id=state.get("agent_id"),
                operation="db_query",
                label="nl2sql_db_execution",
                session_id=state.get("session_id"),
                request_id=state.get("request_id"),
                operation_id="sql_exec",
                metadata={"sql_query": state.get("sql_query"), "success": True},
                metrics=[
                    {"name": "duration_ms", "value": float(execution_time * 1000.0)},
                    {"name": "rows_returned", "value": float(rows_count)},
                ],
            )
        except Exception as e:
            logger.warning(f"Failed to record sql_exec usage event (non-blocking): {e}")
    else:
        logger.error(f"node_sql_exec: SQL execution failed: {err}")
        state["db_result"] = []
        state["sql_error"] = err

        # Count the failed execution against the node, so the health breakdown shows
        # which stage is erroring and not just that the query was unanswered.
        record_node_seconds(state, "sql_exec", execution_time, errors=1)
        state["sql_exec_ms"] = state.get("sql_exec_ms", 0) + int(execution_time * 1000)


        # Record usage event for failed execution (non-blocking)
        try:
            tracker = get_usage_tracker()
            usage_payload_fail = {
                "owner_id": state.get("owner_id"),
                "service_id": state.get("agent_id"),
                "service_type": os.getenv("USAGE_SERVICE_TYPE", "nl2sql"),
                "operation": "db_query",
                "label": "nl2sql_db_execution",
                "session_id": state.get("session_id"),
                "request_id": state.get("request_id"),
                "operation_id": "sql_exec",
                "metadata": {"sql_query": state.get("sql_query"), "success": False, "error": str(err)[:500]},
                "metrics": [
                    {"name": "duration_ms", "value": float(execution_time * 1000.0)},
                    {"name": "rows_returned", "value": 0.0},
                ],
            }
            logger.info(f"Usage (local) sql_exec failure payload={json.dumps(usage_payload_fail)}")
            await tracker.record_event(
                owner_id=state.get("owner_id"),
                agent_id=state.get("agent_id"),
                operation="db_query",
                label="nl2sql_db_execution",
                session_id=state.get("session_id"),
                request_id=state.get("request_id"),
                operation_id="sql_exec",
                metadata={"sql_query": state.get("sql_query"), "success": False, "error": str(err)[:500]},
                metrics=[
                    {"name": "duration_ms", "value": float(execution_time * 1000.0)},
                    {"name": "rows_returned", "value": 0.0},
                ],
            )
        except Exception as e:
            logger.warning(f"Failed to record sql_exec usage event (non-blocking): {e}")
        
    logger.info(
        "[WF] step.end=sql_exec | request_id=%s | session_id=%s | ok=%s | rows=%d",
        state.get("request_id"),
        state.get("session_id"),
        not bool(state.get("sql_error")),
        len(state.get("db_result") or []),
    )
    return state

