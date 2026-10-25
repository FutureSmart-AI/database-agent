"""
Cross-DB fan-out node (multi-db-spec.md §11).

Runs each sub-question from `cross_db_plan` through the normal single-DB pipeline
(select_and_fewshots → sql_gen → sql_exec, with the usual retry-on-error loop), each scoped to
its own database. The sub-questions run concurrently, every one on its OWN isolated sub-state so
they cannot clobber each other's selected_tables / sql_query / db_result.

Per-DB results are collected into state["cross_db_results"] as:
    [ {db_id, columns, rows, sql_query, error} , ... ]
`cross_db_merge` then joins them in-application.
"""
import os
import asyncio
from typing import Dict, Any, List

from langgraph.graph import StateGraph, START, END
from langsmith import traceable

from agent.state import AgentState
from agent.nodes.select_table_and_fewshots import node_select_and_fewshots
from agent.nodes.sql_gen import node_sql_gen
from agent.nodes.sql_exec import node_sql_exec
from logger import logger
from otel_tracing import track_time

# Connection fields copied into each sub-query's runtime_db_details.
_DB_FIELDS = ("db_id", "db_host", "db_name", "db_user", "db_password", "db_port", "db_engine")


def _route_after_subquery_exec(state: AgentState) -> str:
    """Retry sql_gen on a retryable SQL error, else finish this sub-query.

    Mirrors runner.route_after_sql_exec's retry policy but WITHOUT the pandas/final_answer
    fan-in — a sub-query only needs to produce rows (or give up).
    """
    max_retries = int(os.getenv("SQL_MAX_RETRIES", "2"))
    if state.get("sql_error") and state.get("retry_count", 0) < max_retries:
        return "sql_gen"
    return "END"


def _build_single_db_subgraph():
    """Compile the reusable single-DB core: select → generate → execute (+retry)."""
    sg = StateGraph(AgentState)
    sg.add_node("select_and_fewshots", node_select_and_fewshots)
    sg.add_node("sql_gen", node_sql_gen)
    sg.add_node("sql_exec", node_sql_exec)
    sg.add_edge(START, "select_and_fewshots")
    sg.add_edge("select_and_fewshots", "sql_gen")
    sg.add_edge("sql_gen", "sql_exec")
    sg.add_conditional_edges(
        "sql_exec",
        _route_after_subquery_exec,
        {"sql_gen": "sql_gen", "END": END},
    )
    return sg.compile()


# Compiled once at import — reused for every sub-query across all requests.
single_db_subgraph = _build_single_db_subgraph()


@traceable(run_type="chain", name="node_cross_db_fanout")
@track_time("Node: Cross-DB Fan-out")
async def node_cross_db_fanout(state: AgentState) -> AgentState:
    """Answer every sub-question against its own DB concurrently and collect the result sets."""
    request_id = state.get("request_id")
    plan = state.get("cross_db_plan") or {}
    sub_questions: List[Dict[str, Any]] = plan.get("sub_questions") or []
    by_id = {d.get("db_id"): d for d in (state.get("selected_dbs") or [])}
    logger.info(
        "[WF] step.start=cross_db_fanout | request_id=%s | n_sub_questions=%d",
        request_id, len(sub_questions),
    )

    if not sub_questions:
        state["cross_db_results"] = []
        return state

    async def _run_one(sq: Dict[str, Any]) -> Dict[str, Any]:
        db_id = sq.get("db_id")
        db = by_id.get(db_id) or {}
        runtime = {k: db.get(k) for k in _DB_FIELDS}
        # The join is only correct if each side is COMPLETE over the join key — a LIMITed
        # sub-result silently drops join candidates. Few-shot examples often bias sql_gen
        # toward adding LIMITs, so state the requirement explicitly in the sub-question.
        question = (sq.get("question", "") +
                    " Return the complete result set; do not add a LIMIT unless this question explicitly asks for a top N.")
        # Isolated sub-state: only what the single-DB core reads. The sub-question becomes the
        # refined_query so the whole pipeline (table selection, few-shots, HC, SQL) is focused.
        sub_state: AgentState = {
            "query": question,
            "refined_query": question,
            "past_messages": [],
            "agent_id": state.get("agent_id"),
            "owner_id": state.get("owner_id"),
            "user_id": state.get("user_id"),
            "session_id": state.get("session_id"),
            "request_id": request_id,
            "db_id": db_id,
            "runtime_db_details": runtime,
        }
        try:
            result = await single_db_subgraph.ainvoke(sub_state)
            return {
                "db_id": db_id,
                "columns": result.get("db_columns") or [],
                "rows": result.get("db_result") or [],
                "sql_query": result.get("sql_query"),
                "selected_tables": result.get("selected_tables") or [],
                "error": result.get("sql_error"),
                "answerability_error": result.get("answerability_error"),
                "access_policy_error": result.get("access_policy_error"),
                "access_denied_tables": result.get("access_denied_tables") or [],
            }
        except Exception as e:  # noqa: BLE001 — one failed sub-query must not kill the others
            logger.error("[cross_db_fanout] sub-query failed for db_id=%s: %s", db_id, e)
            return {
                "db_id": db_id,
                "columns": [],
                "rows": [],
                "sql_query": None,
                "selected_tables": [],
                "error": str(e),
            }

    results = await asyncio.gather(*[_run_one(sq) for sq in sub_questions])
    state["cross_db_results"] = results
    logger.info(
        "[WF] step.end=cross_db_fanout | request_id=%s | results=%s",
        request_id,
        [{"db_id": r["db_id"], "rows": len(r["rows"]), "error": bool(r["error"])} for r in results],
    )
    return state
