"""Usage event tracking for NL2SQL agent operations.

Events are written to NL2SQL's OWN `usage_events` / `usage_metrics` tables
(`chatbot_management.db_utils.usage_event_recording`), and — while the platform dashboard
still reads the central service — MIRRORED there over HTTP as well.

Why both, for now: the dashboard's Usage & Limits card calls
`POST /api/usage/v1/analytics/query` on the usage service. If NL2SQL stopped posting
there, that card would go blank for NL2SQL until the frontend is repointed. Writing to
both keeps the existing screen working while NL2SQL builds its own history, and the mirror
is one environment variable to switch off afterwards:

    USAGE_SERVICE_MIRROR=false      stop posting to the central service

The local write is the one that matters and happens first; the mirror is best-effort. If
the central service is unreachable, NL2SQL still has the event.

Also fixed here: the URL and API key used to be hardcoded to production, so STAGING wrote
its events into the production usage service. Both now come from the environment.

Recording stays FIRE-AND-FORGET, and the public surface is unchanged —
`get_usage_tracker()`, `record_event`, `record_llm_call`, `record_sql_execution`,
`record_graph_generation` — so no call site needed editing.
"""

import asyncio
import os
import json
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set
import httpx
from logger import logger


USAGE_SERVICE_TYPE = "nl2sql"

# Mirror to the central usage service as well as writing locally. On by default so the
# platform dashboard keeps working; set false once its Usage card reads NL2SQL instead.
USAGE_SERVICE_MIRROR = os.getenv("USAGE_SERVICE_MIRROR", "true").strip().lower() != "false"

# From the environment, not hardcoded — a literal production URL here meant staging wrote
# into production. Empty disables the mirror regardless of the flag above.
USAGE_API_URL = os.getenv("USAGE_API_URL", "").strip()
USAGE_API_KEY = os.getenv("USAGE_API_KEY", "").strip()

# Circuit-breaker: when the tracking endpoint fails, skip subsequent events
# for this many seconds to avoid 15s timeouts piling up across a single request.
CIRCUIT_OPEN_SECONDS = float(60)


class UsageTracker:
    """Non-blocking usage event tracker with circuit breaker."""

    def __init__(self, api_url: str = None, api_key: str = None):
        # Kept as attributes because csv_agent/node.py reads `tracker.api_url` for a log line.
        self.api_url = api_url if api_url is not None else USAGE_API_URL
        self.api_key = api_key if api_key is not None else USAGE_API_KEY
        self._client: Optional[httpx.AsyncClient] = None
        # Circuit breaker — when > now, skip all tracking calls.
        self._circuit_open_until: float = 0.0
        # Hold strong references to background tasks so Python's GC doesn't
        # cancel them while they're in flight (asyncio.create_task only holds
        # a weak reference).
        self._tasks: Set[asyncio.Task] = set()

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client with aggressive per-phase timeouts."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    connect=1.0,   # fail fast if endpoint unreachable
                    read=2.0,      # tracking endpoint should respond quickly
                    write=1.0,
                    pool=1.0,
                ),
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
            )
        return self._client

    async def _close_client(self):
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    def _circuit_is_open(self) -> bool:
        return time.monotonic() < self._circuit_open_until

    def _open_circuit(self, reason: str) -> None:
        self._circuit_open_until = time.monotonic() + CIRCUIT_OPEN_SECONDS
        logger.warning(
            "[USAGE] tracking circuit OPEN for %.0fs — skipping events. reason=%s",
            CIRCUIT_OPEN_SECONDS, reason,
        )
    
    async def record_event(
        self,
        owner_id: Optional[str],
        agent_id: Optional[str],
        operation: str,
        label: Optional[str] = None,
        session_id: Optional[str] = None,
        request_id: Optional[str] = None,
        operation_id: Optional[str] = None,
        key_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        metrics: Optional[List[Dict[str, float]]] = None,
    ) -> None:
        """
        Record a usage event (non-blocking).
        
        Args:
            owner_id: User/owner identifier
            agent_id: Agent identifier
            operation: Operation name (e.g., "llm_call", "sql_execution", "graph_generation")
            label: Optional label for the event
            session_id: Session identifier for linking events
            request_id: Request identifier for linking events
            operation_id: Operation identifier
            metadata: Additional metadata
            metrics: List of metrics with name and value
        """
        # Skip entirely if the circuit is open (endpoint recently failed).
        # This prevents 15s connect-timeouts from piling up across one request.
        if self._circuit_is_open():
            return

        # Build timestamp without microseconds and slightly in the past to avoid drift issues
        ts = (datetime.utcnow() - timedelta(seconds=1)).replace(microsecond=0).isoformat() + "Z"
        owner = owner_id or ""

        # According to API requirements, at least one of owner_id, agent_id, or service_id must be provided
        event = {
            "owner_id": owner if owner else None,
            # Both carry the agent id. `service_id` is what this service has always sent
            # and the central analytics resolves agents through it; `agent_id` is what
            # NL2SQL's own owner-level reads group by. Same id space here.
            "agent_id": agent_id if agent_id else None,
            "service_id": agent_id if agent_id else None,
            "service_type": USAGE_SERVICE_TYPE,
            "operation": operation,
            "label": label or operation,
            "session_id": session_id or "",
            "request_id": request_id or "",
            "operation_id": operation_id or "",
            "timestamp": ts,
            "key_type": key_type,
            "metadata": metadata or {},
            "metrics": metrics or [],
        }

        # Fire-and-forget — hold a reference so the task isn't GC'd in flight
        # (asyncio.create_task keeps only a weak one).
        task = asyncio.create_task(self._dispatch([event]))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _dispatch(self, events: List[Dict[str, Any]]) -> None:
        """Write locally, then mirror to the central service if enabled.

        Local first and awaited separately so a slow or dead central service cannot stop
        NL2SQL recording its own usage. Neither leg can raise into the caller.
        """
        await self._store_local(events)
        if USAGE_SERVICE_MIRROR and self.api_url and self.api_key:
            await self._send_event(events)

    async def _store_local(self, events: List[Dict[str, Any]]) -> None:
        """Persist to NL2SQL's own usage_events / usage_metrics. Never raises."""
        try:
            # Imported lazily: this module is pulled in by graph nodes, and the recording
            # layer reaches the models and session factory — keeping it out of module
            # scope avoids an import cycle through models.sql_models.
            from api.v1.schemas.usage_events import UsageEventRequest
            from chatbot_management.db_utils.usage_event_recording import record_usage_events

            requests = []
            for raw in events:
                try:
                    requests.append(UsageEventRequest(**raw))
                except Exception as e:
                    # A malformed event is a caller bug, not a database problem — log it
                    # and keep the rest of the batch.
                    logger.warning("[USAGE] invalid event %s dropped: %s", raw.get("operation"), e)
            if not requests:
                return

            response = await record_usage_events(requests)
            if response.failed_count:
                logger.warning(
                    "[USAGE] local write: %d recorded, %d failed - %s",
                    response.processed_count, response.failed_count,
                    [f.error for f in response.failed_events][:3],
                )
        except Exception as e:
            logger.warning("[USAGE] local write failed (non-blocking): %s", e)
    
    async def _send_event(self, events: List[Dict[str, Any]]) -> None:
        try:
            client = await self._get_client()
            payload = {"events": events}
            payload_str = json.dumps(payload)
            if len(payload_str) > 4000:
                payload_str = payload_str[:4000] + f"...(truncated {len(json.dumps(payload)) - 4000} chars)"
            logger.info(f"Usage POST {self.api_url} payload={payload_str}")
            response = await client.post(
                self.api_url,
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "x-api-key": self.api_key,
                },
            )
            response.raise_for_status()
            try:
                resp_text = response.text
            except Exception:
                resp_text = None
            ops = ",".join([str(e.get("operation")) for e in events])
            logger.info(f"Usage response ({len(events)} event(s), ops={ops}) status={response.status_code} body={resp_text}")
        except httpx.HTTPStatusError as e:
            content = None
            try:
                content = e.response.text
            except Exception:
                content = None
            logger.warning(f"Failed to record usage event (non-blocking): {e}. Response: {content}")
            # 5xx responses also indicate the backend is unhealthy — open the circuit.
            if 500 <= e.response.status_code < 600:
                self._open_circuit(f"HTTP {e.response.status_code}")
        except (httpx.ConnectTimeout, httpx.ConnectError, httpx.ReadTimeout, httpx.PoolTimeout) as e:
            # Network-level failure → endpoint is unreachable. Stop hammering it.
            self._open_circuit(type(e).__name__)
        except Exception as e:
            logger.warning(f"Failed to record usage event (non-blocking): {e}")
    
    async def record_llm_call(
        self,
        owner_id: Optional[str],
        agent_id: Optional[str],
        operation: str,
        execution_time: float,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        total_tokens: Optional[int] = None,
        extra_metrics: Optional[List[Dict[str, float]]] = None,
        session_id: Optional[str] = None,
        request_id: Optional[str] = None,
        operation_id: Optional[str] = None,
        model_name: Optional[str] = None,
        key_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record an LLM call event with token and timing metrics."""
        metrics: List[Dict[str, float]] = []
        if input_tokens is not None:
            metrics.append({"name": "input_tokens", "value": float(input_tokens)})
        if output_tokens is not None:
            metrics.append({"name": "output_tokens", "value": float(output_tokens)})
        if total_tokens is not None:
            metrics.append({"name": "total_tokens", "value": float(total_tokens)})
        metrics.append({"name": "execution_time_seconds", "value": execution_time})
        if extra_metrics:
            for m in extra_metrics:
                try:
                    n = str(m.get("name"))
                    v = float(m.get("value"))
                    metrics.append({"name": n, "value": v})
                except Exception:
                    continue
        
        event_metadata = metadata or {}
        if model_name:
            event_metadata["model_name"] = model_name
        
        await self.record_event(
            owner_id=owner_id,
            agent_id=agent_id,
            operation=operation,
            label=f"{operation}_llm",
            session_id=session_id,
            request_id=request_id,
            operation_id=operation_id,
            key_type=key_type,
            metadata=event_metadata,
            metrics=metrics,
        )
    
    async def record_sql_execution(
        self,
        owner_id: Optional[str],
        agent_id: Optional[str],
        execution_time: float,
        rows_returned: int,
        session_id: Optional[str] = None,
        request_id: Optional[str] = None,
        operation_id: Optional[str] = None,
        sql_query: Optional[str] = None,
        success: bool = True,
        key_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record a SQL execution event with timing and row count metrics."""
        metrics = [
            {"name": "execution_time_seconds", "value": execution_time},
            {"name": "rows_returned", "value": float(rows_returned)},
        ]
        
        event_metadata = metadata or {}
        if sql_query:
            # Truncate long queries for metadata
            event_metadata["sql_query"] = sql_query[:500] if len(sql_query) > 500 else sql_query
        event_metadata["success"] = success
        
        await self.record_event(
            owner_id=owner_id,
            agent_id=agent_id,
            operation="sql_execution",
            label="sql_execution",
            session_id=session_id,
            request_id=request_id,
            operation_id=operation_id,
            key_type=key_type,
            metadata=event_metadata,
            metrics=metrics,
        )
    
    async def record_graph_generation(
        self,
        owner_id: Optional[str],
        agent_id: Optional[str],
        execution_time: float,
        chart_type: Optional[str] = None,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        total_tokens: Optional[int] = None,
        extra_metrics: Optional[List[Dict[str, float]]] = None,
        session_id: Optional[str] = None,
        request_id: Optional[str] = None,
        operation_id: Optional[str] = None,
        key_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record a graph generation event with timing metrics."""
        metrics = []
        if input_tokens is not None:
            metrics.append({"name": "input_tokens", "value": float(input_tokens)})
        if output_tokens is not None:
            metrics.append({"name": "output_tokens", "value": float(output_tokens)})
        if total_tokens is not None:
            metrics.append({"name": "total_tokens", "value": float(total_tokens)})
        metrics.append({"name": "execution_time_seconds", "value": execution_time})
        if extra_metrics:
            for m in extra_metrics:
                try:
                    n = str(m.get("name"))
                    v = float(m.get("value"))
                    metrics.append({"name": n, "value": v})
                except Exception:
                    continue
        
        event_metadata = metadata or {}
        if chart_type:
            event_metadata["chart_type"] = chart_type
        
        await self.record_event(
            owner_id=owner_id,
            agent_id=agent_id,
            operation="chart_generation",
            label="chart_generation",
            session_id=session_id,
            request_id=request_id,
            operation_id=operation_id,
            key_type=key_type,
            metadata=event_metadata,
            metrics=metrics,
        )


# Global instance
_usage_tracker: Optional[UsageTracker] = None


def get_usage_tracker() -> UsageTracker:
    """Get the global usage tracker instance."""
    global _usage_tracker
    if _usage_tracker is None:
        _usage_tracker = UsageTracker()
    return _usage_tracker
