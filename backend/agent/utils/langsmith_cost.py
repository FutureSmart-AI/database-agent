"""LangSmith as the pricing source for Agent Health.

Tokens and latency are measured locally (``agent.utils.node_metrics``); COST is not —
inventing a price locally would need a model price table kept in sync with every provider,
and the resulting number would be indistinguishable downstream from a real one. LangSmith
already prices every traced run, so the health rows read their cost from it.

Three entry points, all synchronous (callers wrap them in ``asyncio.to_thread``) and all
returning ``{}`` / ``[]`` rather than raising — a monitoring read must never take down a
request:

- :func:`fetch_run_usage`          one run's tokens + cost, by run id
- :func:`fetch_agent_costs`        a whole window's runs for one agent, keyed by chat_id
- :func:`fetch_run_node_breakdown` per-node cost/tokens from a run's child spans

A run is priced ASYNCHRONOUSLY by LangSmith: tokens appear immediately, cost lands
seconds later. Every function here treats "tokens but no cost yet" as a normal result, and
the caller writes what it got — which is why ``cost_usd`` stays NULL instead of 0.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from logger import logger

# The graph's root run name (agent/runner.py's @traceable). Used to pick the run that
# rolls up a whole query rather than one of its child spans.
ROOT_RUN_NAME = "NL2SQL LangGraph"


def _client():
    """A LangSmith client, or None when tracing isn't configured for this environment."""
    if not (os.getenv("LANGCHAIN_API_KEY") or os.getenv("LANGSMITH_API_KEY")):
        return None
    try:
        from langsmith import Client
        return Client()
    except Exception as e:
        logger.warning("[langsmith_cost] client unavailable: %s", e)
        return None


def _project() -> Optional[str]:
    return os.getenv("LANGCHAIN_PROJECT") or os.getenv("LANGSMITH_PROJECT")


def _num(value: Any) -> Optional[float]:
    """Cost fields come back as Decimal/str/None depending on SDK version."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _usage_from_run(run: Any) -> Dict[str, Any]:
    """Normalize one LangSmith run into ``{input_tokens, output_tokens, total_tokens,
    cost_usd}``. ``cost_usd`` is None while the run is unpriced — never 0."""
    it = getattr(run, "prompt_tokens", None)
    ot = getattr(run, "completion_tokens", None)
    tt = getattr(run, "total_tokens", None)
    total_cost = _num(getattr(run, "total_cost", None))
    if total_cost is None:
        # Older payloads carry only the two halves; sum them when at least one is priced.
        pc, cc = _num(getattr(run, "prompt_cost", None)), _num(getattr(run, "completion_cost", None))
        if pc is not None or cc is not None:
            total_cost = (pc or 0.0) + (cc or 0.0)
    return {
        "input_tokens": int(it) if it is not None else None,
        "output_tokens": int(ot) if ot is not None else None,
        "total_tokens": int(tt) if tt is not None else None,
        "cost_usd": total_cost,
    }


def fetch_run_usage(run_id: str) -> Dict[str, Any]:
    """One run's tokens + cost by run id. ``{}`` when unavailable.

    This is the path that needs no project name and no metadata filter — the health row
    stored the run id when the query ran, so this works even if LANGCHAIN_PROJECT changes.
    """
    client = _client()
    if not client or not run_id:
        return {}
    try:
        run = client.read_run(run_id)
    except Exception as e:
        logger.debug("[langsmith_cost] read_run(%s) failed: %s", run_id, e)
        return {}
    usage = _usage_from_run(run)
    if usage["cost_usd"] is None and usage["total_tokens"] is None:
        return {}  # nothing useful yet — let the caller leave the row untouched
    return usage


def fetch_agent_costs(agent_id: str, since: datetime, until: datetime) -> Dict[str, Dict[str, Any]]:
    """Every root run for one agent in ``[since, until)``, keyed by ``chat_id``.

    Matches the health rows through the ``chat_id`` stamped on the run's metadata by
    ``agent.runner.run_agent_flow``. Runs from before that metadata shipped have no
    chat_id and are skipped here — :func:`fetch_run_usage` prices those by run id instead.
    """
    client = _client()
    project = _project()
    if not client or not agent_id:
        return {}
    if not project:
        logger.warning("[langsmith_cost] LANGCHAIN_PROJECT unset — metadata rollup unavailable")
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    try:
        runs = client.list_runs(
            project_name=project,
            is_root=True,
            start_time=since,
            filter=f'and(eq(metadata_key, "agent_id"), eq(metadata_value, "{agent_id}"))',
        )
        for run in runs:
            # list_runs' start_time is a lower bound only, so close the window here.
            started = getattr(run, "start_time", None)
            if isinstance(started, datetime):
                started_naive = started.replace(tzinfo=None) if started.tzinfo else started
                if started_naive >= until:
                    continue
            meta = (getattr(run, "extra", None) or {}).get("metadata") or {}
            chat_id = meta.get("chat_id")
            if not chat_id:
                continue
            usage = _usage_from_run(run)
            if usage["cost_usd"] is None and usage["total_tokens"] is None:
                continue
            out[chat_id] = usage
    except Exception as e:
        logger.warning("[langsmith_cost] list_runs for agent=%s failed: %s", agent_id, e)
        return {}
    return out


# Child-span name → the graph node it belongs to. LangGraph names its spans after the
# node, but the LLM call inside shows up under the model's own name, so we attribute a
# span to the nearest ancestor that IS a node.
_KNOWN_NODES = {
    "router", "db_router", "select_and_fewshots", "cross_db_fanout", "cross_db_merge",
    "sql_gen", "sql_exec", "check_pandas", "check_pandas_needed", "invoke_pandas",
    "final_answer", "final_answer_node", "graph_agent",
}

# Spans whose node name differs from the graph node's key.
_NODE_ALIASES = {
    "final_answer_node": "final_answer",
    "check_pandas_needed": "check_pandas",
}


def fetch_run_node_breakdown(run_id: str) -> List[Dict[str, Any]]:
    """Per-node cost and tokens for one query, from the run's child spans.

    Returns entries shaped like the local capture (``node_name``, ``model``, token counts)
    plus the priced fields (``input_cost``, ``output_cost``, ``total_cost``), so the
    storage layer can merge them into what the nodes already recorded. ``[]`` when the run
    has no children or LangSmith is unavailable — the local capture then stands alone.
    """
    client = _client()
    if not client or not run_id:
        return []
    try:
        children = list(client.list_runs(trace_id=run_id, is_root=False))
    except Exception as e:
        logger.debug("[langsmith_cost] list_runs(trace=%s) failed: %s", run_id, e)
        return []

    by_id = {str(getattr(r, "id", "")): r for r in children}

    def _node_of(run: Any) -> Optional[str]:
        """Walk up to the nearest ancestor span that names a graph node."""
        seen = 0
        cur = run
        while cur is not None and seen < 12:  # depth guard: never loop on a cyclic parent
            name = getattr(cur, "name", None)
            if name in _KNOWN_NODES:
                return _NODE_ALIASES.get(name, name)
            cur = by_id.get(str(getattr(cur, "parent_run_id", "") or ""))
            seen += 1
        return None

    agg: Dict[str, Dict[str, Any]] = {}
    for run in children:
        if getattr(run, "run_type", None) != "llm":
            continue  # only LLM spans carry price
        node = _node_of(run)
        if not node:
            continue
        usage = _usage_from_run(run)
        entry = agg.setdefault(node, {
            "node_name": node, "model": None,
            "input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
            "input_cost": 0.0, "output_cost": 0.0, "total_cost": 0.0,
        })
        entry["input_tokens"] += usage["input_tokens"] or 0
        entry["output_tokens"] += usage["output_tokens"] or 0
        entry["total_tokens"] += usage["total_tokens"] or 0
        entry["input_cost"] += _num(getattr(run, "prompt_cost", None)) or 0.0
        entry["output_cost"] += _num(getattr(run, "completion_cost", None)) or 0.0
        entry["total_cost"] += usage["cost_usd"] or 0.0
        if not entry["model"]:
            meta = (getattr(run, "extra", None) or {}).get("invocation_params") or {}
            entry["model"] = meta.get("model") or meta.get("model_name") or getattr(run, "name", None)

    for entry in agg.values():
        for key in ("input_cost", "output_cost", "total_cost"):
            entry[key] = round(entry[key], 8)
    return list(agg.values())
