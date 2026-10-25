"""Agent Health — build one health event per query and hand it to storage.

The chat flow calls :func:`send_query_event` once per answered (or failed) query. This
module owns the CLASSIFICATION: turning the agent's result state into the small vocabulary
the analytics APIs aggregate on — ``route``, ``status``, ``failure_category``,
``failed_stage`` — plus the metrics roll-up from ``node_events``.

Ported from the orchestrator's ``agent_health_service``, where NL2SQL was one route among
rag / integration / custom_action. Standing alone, the interesting routing is NL2SQL's
own: which path answered the question (single-DB SQL, cross-DB, pandas, or a direct
router answer) and which node failed when one didn't.

Everything here is best-effort: monitoring must never fail a user's query, so every entry
point swallows its exceptions.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from logger import logger
from agent.utils.node_metrics import KEY_TYPE_MIXED, get_node_events
from agent.utils.model_pricing import answer_usage, node_cost, price_table_version

# Nodes that spend money/time, in graph order — used to order `nodes_used`.
_NODE_ORDER = [
    "router", "db_router", "select_and_fewshots", "cross_db_fanout", "cross_db_merge",
    "sql_gen", "sql_exec", "check_pandas", "invoke_pandas", "final_answer", "graph_agent",
]

# Which node a failure is attributed to, by the signal that identifies it.
_STAGE_BY_SIGNAL = {
    "sql_error": "sql_exec",
    "no_sql": "sql_gen",
    "router_end": "router",
}


def _utc_now_z() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def _rows_returned(result: Dict[str, Any]) -> Optional[int]:
    rows = result.get("db_result")
    if isinstance(rows, (list, tuple)):
        return len(rows)
    return None


def classify_route(result: Dict[str, Any]) -> str:
    """Which path answered the question.

    ``direct_answer`` means the router replied without touching a database (a greeting, a
    clarification, an out-of-scope question) — those must stay distinguishable from SQL
    queries, or the success rate of the actual SQL pipeline is diluted by small talk.
    """
    if result.get("cross_db"):
        return "cross_db"
    if (result.get("action") or "").upper() == "END" and not result.get("sql_query"):
        return "direct_answer"
    if result.get("pandas_execution_result") or result.get("pandas_plan"):
        return "pandas"
    return "sql"


def classify_outcome(result: Dict[str, Any], error: Optional[BaseException] = None) -> Dict[str, Any]:
    """Return ``{status, is_answered, failure_category, failed_stage, failure_detail}``.

    ``status`` is binary — ``answered`` / ``no_answer`` — plus ``error`` for a request that
    raised before it could produce an answer. The failure fields are only set when the
    query was NOT answered, so a successful row never carries a stale category.
    """
    if error is not None:
        return {
            "status": "error", "is_answered": False,
            "failure_category": "exception",
            "failed_stage": "chat_api",
            "failure_detail": f"{type(error).__name__}: {error}"[:2000],
        }

    final_text = result.get("response") or ""
    is_answered = result.get("is_answered")
    if is_answered is None:
        # Mirrors build_chat_response: answered unless an error was surfaced or there is
        # no text at all.
        is_answered = bool(final_text) and not (result.get("error") or result.get("sql_error"))
    is_answered = bool(is_answered)

    if is_answered:
        return {"status": "answered", "is_answered": True, "failure_category": None,
                "failed_stage": None, "failure_detail": None}

    sql_error = result.get("sql_error")
    hard_error = result.get("error")
    sql_query = result.get("sql_query")
    route = classify_route(result)

    if sql_error:
        detail = str(sql_error)[:2000]
        low = detail.lower()
        # A connection-level failure is an operator problem (credentials, network, the
        # database being down); a syntax/semantic failure is a model problem. Splitting
        # them is the whole point of the category — they go to different people.
        if any(k in low for k in ("could not connect", "connection refused", "timed out",
                                  "access denied", "authentication", "no such host",
                                  "connection reset", "operationalerror")):
            category, stage = "db_connection", "sql_exec"
        else:
            category, stage = "sql_error", _STAGE_BY_SIGNAL["sql_error"]
        return {"status": "no_answer", "is_answered": False, "failure_category": category,
                "failed_stage": stage, "failure_detail": detail}

    if hard_error:
        return {"status": "error", "is_answered": False, "failure_category": "exception",
                "failed_stage": "agent_flow", "failure_detail": str(hard_error)[:2000]}

    # A node that reported an error means the PIPELINE broke — a provider outage, a rate
    # limit, malformed structured output — not that the question was unanswerable. Checked
    # before the out-of-scope branch below, because a failed router still ends the run with
    # a canned reply and would otherwise be filed as the user asking the wrong thing.
    # SQL failures are already classified above, where the error text says more.
    failed_node = next((e.get("node_name") for e in get_node_events(result)
                        if int(e.get("errors") or 0) > 0), None)
    if failed_node:
        return {"status": "no_answer", "is_answered": False, "failure_category": "llm_error",
                "failed_stage": failed_node,
                "failure_detail": (final_text or f"{failed_node} reported an error")[:2000]}

    if route == "direct_answer":
        # The router chose to answer directly and the answer wasn't usable — an
        # out-of-scope or unclear question, not a pipeline fault.
        return {"status": "no_answer", "is_answered": False,
                "failure_category": "out_of_scope", "failed_stage": _STAGE_BY_SIGNAL["router_end"],
                "failure_detail": (final_text or None) and final_text[:2000]}

    if not sql_query:
        return {"status": "no_answer", "is_answered": False,
                "failure_category": "sql_generation", "failed_stage": _STAGE_BY_SIGNAL["no_sql"],
                "failure_detail": "no SQL was generated for the question"}

    rows = _rows_returned(result)
    if rows == 0:
        # SQL ran fine and the database had nothing to say. Usually a schema/description
        # mismatch rather than a bug, so it gets its own category.
        return {"status": "no_answer", "is_answered": False, "failure_category": "no_rows",
                "failed_stage": "sql_exec", "failure_detail": "query returned zero rows"}

    return {"status": "no_answer", "is_answered": False, "failure_category": "unanswered",
            "failed_stage": "final_answer",
            "failure_detail": "the answer step could not answer from the result set"}


def _roll_up_nodes(node_events: List[Dict[str, Any]], result: Dict[str, Any]) -> Dict[str, Any]:
    """Sum the per-node capture into query-level tokens, and pick the headline model.

    The headline ``model`` is the ANSWER model (final_answer), because that is the one an
    operator recognises as "the agent's model"; per-node models stay in ``node_data``.
    """
    in_tok = sum(int(e.get("input_tokens") or 0) for e in node_events)
    out_tok = sum(int(e.get("output_tokens") or 0) for e in node_events)
    tot_tok = sum(int(e.get("total_tokens") or 0) for e in node_events)
    # `total_tokens` on state is the pipeline's own running count; prefer whichever is
    # larger so a node we don't capture yet (db_router) can't shrink the total.
    state_tokens = int(result.get("total_tokens") or 0)
    tot_tok = max(tot_tok, state_tokens)
    # The run-level count (model_pricing.collect_llm_usage) includes every model call,
    # recorded by a node or not; the chat API's usage block reports the same totals.
    llm_usage = result.get("llm_usage")
    if isinstance(llm_usage, list) and llm_usage:
        in_tok = sum(int(u.get("input_tokens") or 0) for u in llm_usage)
        out_tok = sum(int(u.get("output_tokens") or 0) for u in llm_usage)
        tot_tok = in_tok + out_tok

    answer_node = next((e for e in node_events if e.get("node_name") == "final_answer"), None)
    headline = answer_node or next((e for e in node_events if e.get("model")), None) or {}
    return {
        "input_tokens": in_tok, "output_tokens": out_tok, "total_tokens": tot_tok,
        "provider": headline.get("provider"), "model": headline.get("model"),
        "key_type": roll_up_key_type(node_events),
    }


def roll_up_key_type(node_events: List[Dict[str, Any]]) -> Optional[str]:
    """Whose credentials paid for this run: "owner-key", "platform-key", or "mixed".

    One value per query, from the nodes that actually made an LLM call — nodes with no key
    (sql_exec) are ignored rather than counted as platform spend. Nodes using different
    providers can genuinely land on different sides when the owner has a key for only
    some of them, so a run spanning both reports "mixed" instead of picking a winner.

    None when no node reported a key type at all, which means "not recorded", not
    "platform paid" — the distinction matters for cost attribution, so callers must not
    coerce it to a default.
    """
    kinds = {e.get("key_type") for e in node_events if e.get("key_type")}
    if not kinds:
        return None
    if KEY_TYPE_MIXED in kinds or len(kinds) > 1:
        return KEY_TYPE_MIXED
    return kinds.pop()


def _ordered_nodes(node_events: List[Dict[str, Any]]) -> List[str]:
    names: Set[str] = {e.get("node_name") for e in node_events if e.get("node_name")}
    ordered = [n for n in _NODE_ORDER if n in names]
    return ordered + sorted(names - set(ordered))


def _unrecorded_calls(node_events, result, latency_ms) -> List[Dict[str, Any]]:
    """Model calls of the run that no node recorded, per model, priced like the nodes."""
    usage = answer_usage(node_events, latency_ms, result.get("llm_usage"))
    return [{"node_name": n["node"], "provider": n["provider"], "model": n["model"],
             "input_tokens": n["input_tokens"], "cached_input_tokens": n["cached_input_tokens"],
             "output_tokens": n["output_tokens"], "calls": n["calls"],
             "estimated_cost_usd": n["estimated_cost_usd"], "price_table": price_table_version()}
            for n in usage.get("nodes", []) if n.get("node") == "other_calls"]


def build_query_event(
    *,
    result: Dict[str, Any],
    agent_id: Optional[str],
    owner_id: Optional[str],
    user_id: Optional[str],
    session_id: Optional[str],
    chat_id: str,
    request_id: Optional[str] = None,
    latency_ms: int = 0,
    db_fetch_ms: int = 0,
    from_widget: bool = False,
    key_type: Optional[str] = None,
    error: Optional[BaseException] = None,
) -> Dict[str, Any]:
    """Assemble the health event for one query. Pure — no I/O, so it is safe to unit-test
    and cheap to call on the error path."""
    result = result or {}
    node_events = get_node_events(result)
    outcome = classify_outcome(result, error=error)
    rolled = _roll_up_nodes(node_events, result)
    runtime_db = result.get("runtime_db_details") or {}

    return {
        "event_type": "agent_query",
        "schema_version": 1,
        "timestamp": _utc_now_z(),
        "agent_id": agent_id, "owner_id": owner_id, "user_id": user_id,
        "session_id": session_id, "chat_id": chat_id, "request_id": request_id,
        "trace_id": result.get("trace_id"),
        "langsmith_run_id": result.get("langsmith_run_id") or result.get("trace_id"),
        "query": result.get("query") or result.get("user_query"),
        "refined_query": result.get("refined_query"),
        # routing
        "route": classify_route(result),
        "nodes_used": _ordered_nodes(node_events),
        "db_id": result.get("db_id") or runtime_db.get("db_id"),
        "db_ids": [d.get("db_id") for d in (result.get("selected_dbs") or []) if isinstance(d, dict)],
        "cross_db": bool(result.get("cross_db")),
        "sql_query": result.get("sql_query") or None,
        "selected_tables": result.get("selected_tables") or [],
        "rows_returned": _rows_returned(result),
        "chart_generated": bool((result.get("graph_json") or {}).get("graph_data")),
        "pandas_used": bool(result.get("pandas_execution_result") or result.get("pandas_plan")),
        # outcome
        **outcome,
        # key_type is whose LLM credentials paid, rolled up from the nodes. The caller's
        # own auth method is a different dimension and is already carried by from_widget.
        "from_widget": bool(from_widget), "key_type": key_type or rolled["key_type"],
        "provider": rolled["provider"], "model": rolled["model"],
        "metrics": {
            "latency_ms": int(latency_ms or 0),
            "db_fetch_ms": int(db_fetch_ms or 0),
            "sql_exec_ms": int(result.get("sql_exec_ms") or 0),
            "input_tokens": rolled["input_tokens"],
            "output_tokens": rolled["output_tokens"],
            "total_tokens": rolled["total_tokens"],
            # Cost is LangSmith's to fill in — a locally-invented number here would be
            # indistinguishable from a priced one downstream.
            "cost_usd": None,
            "cost_complete": False,
            "retry_count": int(result.get("retry_count") or 0),
        },
        # Each node also carries a list-price ESTIMATE from its recorded tokens (DA-COST-001:
        # hosted has no LangSmith price). It stays out of metrics.cost_usd, which is reserved
        # for the provider-priced figure, and names the price table it came from.
        "node_data": [dict(e, estimated_cost_usd=node_cost(e), price_table=price_table_version())
                      for e in node_events] + _unrecorded_calls(node_events, result, latency_ms),
    }


async def send_query_event(**kwargs: Any) -> bool:
    """Build and persist the health event for one query. Never raises."""
    try:
        event = build_query_event(**kwargs)
        from chatbot_management.db_utils.agent_health_db_utils import insert_agent_health_event
        stored = await insert_agent_health_event(event)
        if stored and _finalize_enabled():
            # Price the run in the background: LangSmith needs a moment after the trace
            # closes, and the user's response must not wait for it.
            _spawn(finalize_query_cost(event.get("chat_id"), event.get("langsmith_run_id")))
        return stored
    except Exception as e:  # never raise from monitoring
        logger.error("[agent_health] send_query_event failed: %s", e, exc_info=True)
        return False


def _finalize_enabled() -> bool:
    """Auto-pricing is on only when LangSmith tracing is configured for this service."""
    if os.getenv("AGENT_HEALTH_AUTO_COST", "true").strip().lower() in ("0", "false", "no"):
        return False
    return bool(os.getenv("LANGCHAIN_API_KEY") or os.getenv("LANGSMITH_API_KEY"))


# Strong references to in-flight finalizers — asyncio.create_task keeps only a weak one,
# so without this the GC can cancel a pricing task mid-flight (same bug the usage tracker
# guards against).
_TASKS: Set[asyncio.Task] = set()


def _spawn(coro) -> None:
    try:
        task = asyncio.create_task(coro)
        _TASKS.add(task)
        task.add_done_callback(_TASKS.discard)
    except RuntimeError:  # no running loop (sync context) — skip, the manual sync covers it
        coro.close()


async def finalize_query_cost(chat_id: Optional[str], run_id: Optional[str],
                              delay_s: Optional[float] = None) -> bool:
    """Wait for LangSmith to price this run, then write cost/tokens/node costs onto the row.

    LangSmith prices asynchronously, so an immediate read usually returns tokens but no
    cost. We wait once, then read; the manual ``sync-costs`` endpoint is the backstop for
    anything still unpriced (a slow trace, a dropped task, a restart). Never raises.
    """
    if not chat_id or not run_id:
        return False
    try:
        await asyncio.sleep(delay_s if delay_s is not None
                            else float(os.getenv("AGENT_HEALTH_COST_DELAY_S", "20")))
        from agent.utils.langsmith_cost import fetch_run_usage, fetch_run_node_breakdown
        from chatbot_management.db_utils.agent_health_db_utils import (
            update_row_usage_from_langsmith, update_row_node_data,
        )
        usage = await asyncio.to_thread(fetch_run_usage, run_id)
        if not usage:
            return False
        wrote = await update_row_usage_from_langsmith(chat_id, usage)
        nodes = await asyncio.to_thread(fetch_run_node_breakdown, run_id)
        if nodes:
            await update_row_node_data(chat_id, nodes)
        return bool(wrote)
    except Exception as e:  # never raise from monitoring
        logger.warning("[agent_health] finalize_query_cost(%s) failed: %s", chat_id, e)
        return False
