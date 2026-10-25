"""Estimated cost of one answer, from the tokens its model calls used.

Hosted runs without LangSmith tracing, so ``agent_health_service`` never receives a priced
cost (DA-COST-001). This module multiplies recorded tokens by a dated list-price table
(``model_profiles/prices.json``) to give each answer an ESTIMATE.

It is kept distinguishable from a provider-priced number on purpose: the field is called
``estimated_cost_usd`` and always travels with the price-table version it came from. A
model missing from the table makes the total incomplete (``cost_complete=False``) instead
of silently counting as free. Cached-input discounts apply only to tokens the provider
reported as cached.

Totals come from EVERY chat-model call made while the answer was produced, counted per
model by a run-level callback (:func:`collect_llm_usage`) — not only from the nodes that
record ``node_events`` (``agent.utils.node_metrics``). Node entries attribute what they
can; whatever no node recorded (entity resolution, post-processing, any call added later)
is listed per model as ``other_calls``, so an uninstrumented call can never vanish from
the cost. Embedding calls do not pass through chat callbacks and are excluded (named in
``excludes``); at $0.02 per million tokens they are negligible here.

Never raises: a pricing problem must not fail a user's answer.
"""
from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.tracers.context import register_configure_hook

from logger import logger

PRICES_PATH = Path(__file__).resolve().parents[2] / "model_profiles" / "prices.json"
TOKEN_FIELDS = ("input_tokens", "cached_input_tokens", "output_tokens", "calls")


@lru_cache(maxsize=1)
def load_prices() -> Dict[str, Any]:
    try:
        return json.loads(PRICES_PATH.read_text(encoding="utf-8"))
    except Exception as e:  # a missing table means "unpriced", not a failed request
        logger.warning("[model_pricing] price table unavailable: %s", e)
        return {"version": None, "models": {}}


def price_table_version() -> Optional[str]:
    return load_prices().get("version")


def _rate(provider: Optional[str], model: Optional[str]) -> Optional[Dict[str, float]]:
    if not model:
        return None
    models = load_prices().get("models", {})
    return models.get(f"{(provider or 'openai').lower()}/{model}")


def node_cost(event: Dict[str, Any]) -> Optional[float]:
    """USD estimate for one node entry, or None when its model is unpriced."""
    rate = _rate(event.get("provider"), event.get("model"))
    if rate is None:
        return None
    input_tokens = int(event.get("input_tokens") or 0)
    cached = min(int(event.get("cached_input_tokens") or 0), input_tokens)
    output_tokens = int(event.get("output_tokens") or 0)
    cached_rate = rate.get("cached_input", rate["input"])
    usd = ((input_tokens - cached) * rate["input"] + cached * cached_rate
           + output_tokens * rate.get("output", 0)) / 1_000_000
    return round(usd, 8)


# ── Run-level usage: every chat-model call, per model ───────────────────────

class RunUsageHandler(BaseCallbackHandler):
    """Counts the tokens of every chat-model call in the current context, per model.

    The model comes from the standard ``ls_provider``/``ls_model_name`` metadata LangChain
    attaches at call start (the configured alias, which is what the price table is keyed
    by); the tokens from the message's ``usage_metadata`` at call end.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._models: Dict[Any, tuple] = {}
        self.by_model: Dict[tuple, Dict[str, int]] = {}

    def on_chat_model_start(self, serialized, messages, *, run_id, metadata=None, **kwargs) -> None:
        meta = metadata or {}
        params = kwargs.get("invocation_params") or {}
        provider = str(meta.get("ls_provider") or "openai").lower()
        model = meta.get("ls_model_name") or params.get("model") or params.get("model_name")
        with self._lock:
            self._models[run_id] = (provider, model)

    def on_llm_end(self, response, *, run_id, **kwargs) -> None:
        counts = dict.fromkeys(TOKEN_FIELDS, 0)
        counts["calls"] = 1
        for generations in getattr(response, "generations", None) or []:
            for generation in generations:
                usage = getattr(getattr(generation, "message", None), "usage_metadata", None) or {}
                counts["input_tokens"] += int(usage.get("input_tokens") or 0)
                counts["output_tokens"] += int(usage.get("output_tokens") or 0)
                counts["cached_input_tokens"] += int(
                    (usage.get("input_token_details") or {}).get("cache_read") or 0)
        with self._lock:
            key = self._models.pop(run_id, ("unknown", None))
            entry = self.by_model.setdefault(key, dict.fromkeys(TOKEN_FIELDS, 0))
            for field in TOKEN_FIELDS:
                entry[field] += counts[field]

    def snapshot(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [{"provider": p, "model": m, **dict(v)} for (p, m), v in self.by_model.items()]


_RUN_USAGE: ContextVar[Optional[RunUsageHandler]] = ContextVar("database_agent_run_usage", default=None)
register_configure_hook(_RUN_USAGE, True)


@contextmanager
def collect_llm_usage() -> Iterator[RunUsageHandler]:
    """Count every chat-model call made inside this block, including in tasks it spawns."""
    handler = RunUsageHandler()
    token = _RUN_USAGE.set(handler)
    try:
        yield handler
    finally:
        _RUN_USAGE.reset(token)


# ── The per-answer usage block ──────────────────────────────────────────────

def _entry(e: Dict[str, Any]) -> Dict[str, Any]:
    tokens = int(e.get("input_tokens") or 0) + int(e.get("output_tokens") or 0)
    return {
        "node": e.get("node_name"), "provider": e.get("provider"), "model": e.get("model"),
        "input_tokens": int(e.get("input_tokens") or 0),
        "cached_input_tokens": int(e.get("cached_input_tokens") or 0),
        "output_tokens": int(e.get("output_tokens") or 0),
        "latency_ms": int(e["latency_ms"]) if e.get("latency_ms") is not None else None,
        "calls": int(e.get("calls") or 0),
        "estimated_cost_usd": node_cost(e) if tokens else None,
    }


def _key(provider: Optional[str], model: Optional[str]) -> tuple:
    return (provider or "openai").lower(), model


def answer_usage(node_events: List[Dict[str, Any]], latency_ms: Optional[float],
                 llm_usage: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """The per-answer ``usage`` block returned by the chat API.

    ``latency_ms`` is the agent's own processing time for this answer (graph start to
    finish); follow-up suggestions run after it and are not included in either number.
    ``llm_usage`` is :func:`collect_llm_usage`'s per-model count for the same run. When it
    is given it is the authority for the totals, and tokens no node recorded are listed
    per model as ``other_calls``; without it the totals are the nodes' own.
    """
    try:
        nodes = [_entry(e) for e in node_events or []]
        if llm_usage is None:
            sources = [e for e in node_events or []
                       if int(e.get("input_tokens") or 0) + int(e.get("output_tokens") or 0)]
        else:
            sources = list(llm_usage)
            recorded: Dict[tuple, Dict[str, int]] = {}
            for n in nodes:
                if n["model"]:
                    bucket = recorded.setdefault(_key(n["provider"], n["model"]), dict.fromkeys(TOKEN_FIELDS, 0))
                    for field in TOKEN_FIELDS:
                        bucket[field] += n[field]
            for u in llm_usage:
                seen = recorded.get(_key(u.get("provider"), u.get("model")), {})
                rest = {f: max(int(u.get(f) or 0) - int(seen.get(f) or 0), 0) for f in TOKEN_FIELDS}
                if rest["input_tokens"] or rest["output_tokens"]:
                    nodes.append(_entry({"node_name": "other_calls", "provider": u.get("provider"),
                                         "model": u.get("model"), "latency_ms": None, **rest}))
        costs = [node_cost(s) for s in sources]
        return {
            "latency_ms": int(latency_ms) if latency_ms is not None else None,
            "input_tokens": sum(int(s.get("input_tokens") or 0) for s in sources),
            "output_tokens": sum(int(s.get("output_tokens") or 0) for s in sources),
            "estimated_cost_usd": round(sum(c or 0.0 for c in costs), 6) if sources else None,
            "cost_complete": all(c is not None for c in costs),
            "price_table": price_table_version(),
            "excludes": ["follow_up_suggestions", "embeddings"],
            "nodes": nodes,
        }
    except Exception as e:  # never raise from instrumentation
        logger.debug("[model_pricing] usage block skipped: %s", e)
        return {"latency_ms": int(latency_ms) if latency_ms is not None else None}
