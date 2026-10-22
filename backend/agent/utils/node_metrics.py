"""Per-node metric capture for the Agent Health analytics store.

Every LLM node already measures provider, model, token counts and duration in order to
fire a usage event at the external tracking API (``agent.utils.usage_tracking``). That
call is fire-and-forget over the network and the numbers are dropped locally, so nothing
downstream can see how a single query was spent across nodes.

This module keeps the SAME numbers in the graph state, under ``node_events``, so the
health-event writer can persist a per-node breakdown with the query row — no second
service, no trace round-trip, and correct even when tracking or LangSmith is down.
LangSmith later prices these nodes (``agent.utils.langsmith_cost``); tokens and latency
here are the authoritative local values.

Nodes return the whole state dict, so mutating the list in place propagates through
LangGraph's merge. Repeated visits to a node (a sql_gen retry, a cross-DB fan-out) MERGE
into that node's single entry — tokens and latency add up and ``calls`` counts the
visits, so a retry shows as one costly node rather than two half-price ones.

Never raises: a metrics failure must not fail a user's query.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from logger import logger

STATE_KEY = "node_events"

# Reported when one run spent on both the owner's credentials and the platform's — normal
# when nodes use different providers and the owner has a key for only some of them. Worth
# naming rather than collapsing to one side: "owner-key" would understate what we paid for,
# "platform-key" would overstate it.
KEY_TYPE_MIXED = "mixed"


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def record_node_event(
    state: Dict[str, Any],
    node_name: str,
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    input_tokens: Any = None,
    output_tokens: Any = None,
    total_tokens: Any = None,
    latency_ms: Any = None,
    key_type: Optional[str] = None,
    calls: int = 1,
    errors: int = 0,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Record one node's spend on ``state['node_events']``, merging repeat visits.

    ``total_tokens`` defaults to input+output when the callback only reported the split
    (and vice versa is not inferred — a missing split stays 0 rather than guessing).

    ``key_type`` is whose credentials paid for this node's LLM calls ("owner-key" or
    "platform-key"). Every LLM node already resolves it to build its client; capturing it
    here is what lets the run as a whole be attributed (see ``KEY_TYPE_MIXED``). A node
    that makes no LLM call (sql_exec) leaves it None.
    """
    try:
        if not isinstance(state, dict) or not node_name:
            return
        events: List[Dict[str, Any]] = state.get(STATE_KEY) or []
        it, ot = _as_int(input_tokens), _as_int(output_tokens)
        tt = _as_int(total_tokens) or (it + ot)

        entry = next((e for e in events if e.get("node_name") == node_name), None)
        if entry is None:
            entry = {
                "node_name": node_name, "provider": provider, "model": model,
                "input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
                "latency_ms": 0, "calls": 0, "errors": 0,
                "key_type": None,
            }
            events.append(entry)

        entry["input_tokens"] += it
        entry["output_tokens"] += ot
        entry["total_tokens"] += tt
        entry["latency_ms"] += _as_int(latency_ms)
        entry["calls"] += max(1, _as_int(calls))
        entry["errors"] += _as_int(errors)
        # First non-empty wins: a retry that fell back to another model shouldn't erase
        # which model actually did the work first.
        if provider and not entry.get("provider"):
            entry["provider"] = provider
        if model and not entry.get("model"):
            entry["model"] = model
        # A node revisited on a different provider can legitimately switch key type — say
        # a retry falls back to a model the owner has no key for. Record that rather than
        # letting whichever visit came first speak for the whole node.
        if key_type:
            existing = entry.get("key_type")
            if not existing:
                entry["key_type"] = key_type
            elif existing != key_type:
                entry["key_type"] = KEY_TYPE_MIXED
        if extra:
            entry.update({k: v for k, v in extra.items() if v is not None})

        state[STATE_KEY] = events
    except Exception as e:  # never raise from instrumentation
        logger.debug("[node_metrics] skipped %s: %s", node_name, e)


def record_node_seconds(
    state: Dict[str, Any], node_name: str, seconds: Any, **kwargs: Any
) -> None:
    """``record_node_event`` for the many call sites that measure in seconds."""
    try:
        ms = int(float(seconds or 0) * 1000)
    except (TypeError, ValueError):
        ms = 0
    record_node_event(state, node_name, latency_ms=ms, **kwargs)


def get_node_events(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The captured per-node breakdown, safe on a missing/none state."""
    if not isinstance(state, dict):
        return []
    events = state.get(STATE_KEY)
    return list(events) if isinstance(events, list) else []
