"""Usage Events APIs — owner-level usage for the Usage & Limits screens.

One row per billable operation (LLM call, SQL execution, chart generation) with its
metrics. Ported from fs-agent-usage-limits (`routers/usage_events_router.py`), so request
and response shapes match and the dashboard can move over by changing base URL.

WHY THIS AND NOT AGENT HEALTH — they answer different questions:

    Agent Health   one row per CHAT QUERY, agent-scoped, only as old as the feature.
                   "How is this agent performing?" — per-node breakdown, failure stage.
    Usage events   one row per OPERATION, OWNER-scoped, full history.
                   "What is this customer using?" — the Usage & Limits screens.

The Usage screens are owner-level over months, which the health table cannot serve.

NL2SQL's own nodes do NOT post to `/v1/events`. They write in-process via
`agent.utils.usage_tracking` -> `chatbot_management.db_utils.usage_event_recording`, with
no HTTP hop. The POST endpoint exists for parity and for any other producer.

Four deliberate differences from upstream:

  * Auth is this repo's `get_api_key_or_session`, not `require_permission` — that helper
    calls the chat service's `/check-access`, which 404s on agents NL2SQL created (the
    same reason RBAC is off in `agent/utils/authorization.py`). Ownership is scoped inline.
  * A session caller reads only their own usage; the master key sees the fleet; a
    per-agent API key — an auth type upstream has no concept of — is pinned to its agent.
  * On write, session and agent-key callers get `owner_id`/`agent_id` OVERWRITTEN rather
    than trusted. Attribution correctness, not access control: an event billed to the
    wrong owner is corrupt data under any auth model.
  * Upstream's long `description=`/`responses=` decorator blocks are dropped in favour of
    docstrings, matching every other router here.

Endpoints:
  POST /v1/events               record events (bulk, partial success)
  GET  /v1/events               paginated events with filters
  GET  /v1/aggregate            metrics aggregated by chosen dimensions
                                (incl. model/provider, read from the metadata JSONB)
  GET  /v1/trend                usage over time, in rolling buckets ending now
  GET  /v1/summary/{owner_id}   per-service/operation rollup for one owner
"""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.v1.schemas.usage_events import (
    AggregatedUsageResponse,
    UsageEventsListResponse,
    UsageEventsRequest,
    UsageEventsResponse,
    UsageSummaryResponse,
)
from chatbot_management.db_utils.usage_event_recording import record_usage_events
from chatbot_management.db_utils.usage_event_retrieval import (
    TREND_BUCKETS,
    get_aggregated_usage,
    get_usage_events,
    get_usage_summary,
    get_usage_trend,
)
from chatbot_management.services.sqlmodel_session import async_session
from chatbot_management.utils.api_validation import get_api_key_or_session
from logger import logger
from otel_tracing import track_time

router = APIRouter(prefix="/v1", tags=["Usage Events"])

# Dimensions the aggregate endpoint may group by. Anything else is a 422 rather than
# being interpolated into SQL.
# Dimensions worth grouping by here. Anything else is a 422 rather than being
# interpolated into SQL.
#
# `service_id` and `service_type` are deliberately absent even though the columns exist.
# NL2SQL writes the agent id into BOTH agent_id and service_id (service_id is what the
# central usage service resolves agents through), and every row is service_type "nl2sql" —
# so grouping by either returns exactly what agent_id returns, or one single group.
#
# `model` and `provider` are not columns - they are read out of the `metadata` JSONB
# (GIN-indexed) because the Usage screen's model table and all of its breakdown drawers
# split by them. See `_JSON_DIMENSIONS` in usage_event_retrieval for the coalescing rule.
#
# `phase` is the screen's "Functional Label" facet — Checking/Preparing/Extracting/
# Answering. One phase spans several labels, so it cannot be had by filtering `label`
# (which takes a single value) and has to be its own dimension. See PHASE_BY_LABEL.
_GROUP_BY_FIELDS = {"operation", "label", "agent_id", "key_type", "model", "provider",
                    "phase"}


def _scope_reads(auth: dict, owner_id: Optional[str], agent_id: Optional[str]):
    """Narrow a read to what this caller should see. Returns (owner_id, agent_id).

    Not RBAC — see `agent/utils/authorization.py`; a session caller may already reach any
    agent. This decides whose usage is meant when the request does not say, matching
    `analytics.py`'s overview endpoint:

      session        -> own email unless one is named
      master key     -> whatever was asked for, fleet-wide when nothing was
      agent API key  -> pinned to the key's own agent
    """
    auth_type = auth.get("auth_type")
    if auth_type == "session":
        # `user_id` on a session is the caller's email, which is what events store.
        owner_id = owner_id or auth.get("user_id")
    elif auth_type == "agent_api_key":
        agent_id = auth.get("agent_id") or agent_id
    return owner_id, agent_id


@router.post("/events", response_model=UsageEventsResponse, status_code=status.HTTP_200_OK)
@track_time("API: Record Usage Events")
async def api_record_usage_events(
    request: UsageEventsRequest,
    auth: dict = Depends(get_api_key_or_session),
) -> UsageEventsResponse:
    """Record usage events. Always 200 — check the body for per-event failures.

    Partial success by design: one malformed event must not discard the rest of a batch,
    because a fire-and-forget producer cannot retry selectively. Each event gets its own
    transaction; `failed_events` reports the ones that did not land.

    Validation — timestamp window, metric count, metadata depth, and at least one of
    owner_id/agent_id/service_id — happens in `UsageEventsRequest` before this runs.
    """
    logger.info(f"POST /v1/events - {len(request.events)} event(s)")
    try:
        auth_type = auth.get("auth_type")

        if auth_type == "session":
            session_email = auth.get("user_id")
            for event in request.events:
                event.owner_id = session_email

        elif auth_type == "agent_api_key":
            key_agent_id = auth.get("agent_id")
            if not key_agent_id:
                raise HTTPException(status_code=403, detail="API key is not scoped to an agent")
            for event in request.events:
                event.agent_id = key_agent_id
                event.owner_id = auth.get("user_id") or event.owner_id

        response = await record_usage_events(request.events)
        logger.info(
            f"POST /v1/events - {response.processed_count} recorded, {response.failed_count} failed"
        )
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"POST /v1/events - Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An unexpected error occurred")


@router.get("/events", response_model=UsageEventsListResponse)
@track_time("API: Get Usage Events")
async def api_get_usage_events(
    owner_id: Optional[str] = Query(None, description="Defaults to your own email on a session"),
    key_type: Optional[str] = Query(None, description="platform-key | owner-key"),
    agent_id: Optional[str] = Query(None, description="e.g. NL2SQL_39F3787E"),
    operation: Optional[str] = Query(None, description="e.g. llm_call, sql_execution"),
    start_date: Optional[datetime] = Query(None, description="ISO-8601, inclusive"),
    end_date: Optional[datetime] = Query(None, description="ISO-8601, exclusive"),
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    auth: dict = Depends(get_api_key_or_session),
) -> UsageEventsListResponse:
    """Paginated raw events, newest first, each with its metrics."""
    if start_date and end_date and end_date <= start_date:
        raise HTTPException(status_code=422, detail="end_date must be after start_date")

    owner_id, agent_id = _scope_reads(auth, owner_id, agent_id)
    try:
        async with async_session() as session:
            # agent_id is matched against BOTH columns: NL2SQL writes it to agent_id and
            # service_id alike, and older rows (written before agent_id was populated)
            # carry it only in service_id. Passing it as both keeps that history findable.
            return await get_usage_events(
                session, owner_id=owner_id, key_type=key_type, agent_id=agent_id,
                service_id=agent_id, operation=operation, start_date=start_date,
                end_date=end_date, limit=limit, offset=offset,
            )
    except Exception as e:
        logger.error(f"GET /v1/events - Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An unexpected error occurred")


@router.get("/aggregate", response_model=AggregatedUsageResponse)
@track_time("API: Aggregate Usage")
async def api_get_aggregated_usage(
    owner_id: Optional[str] = Query(None, description="Defaults to your own email on a session"),
    key_type: Optional[str] = Query(None, description="platform-key | owner-key"),
    agent_id: Optional[str] = Query(None, description="e.g. NL2SQL_39F3787E"),
    operation: Optional[str] = Query(None),
    label: Optional[str] = Query(None),
    model: Optional[str] = Query(None, description="e.g. openai/gpt-oss-120b"),
    provider: Optional[str] = Query(None, description="e.g. groq, openai"),
    phase: Optional[str] = Query(
        None, description="Functional label: Checking | Preparing | Extracting | Answering"),
    start_date: Optional[datetime] = Query(None, description="ISO-8601, inclusive"),
    end_date: Optional[datetime] = Query(None, description="ISO-8601, exclusive"),
    group_by: List[str] = Query(
        ["operation"],
        description=("Any of: operation, label, agent_id, key_type, model, provider, "
                     "phase"),
    ),
    auth: dict = Depends(get_api_key_or_session),
) -> AggregatedUsageResponse:
    """Metrics summed per group — totals, averages, min/max and counts per metric name.

    This is what an owner-level Usage screen reads: pass `group_by=agent_id` for the
    per-agent table, `group_by=model&group_by=provider` for the model table and the
    breakdown drawers, or leave the default for a service/operation split.

    A `model` or `provider` group of `null` is a real answer, not missing data: database
    and code-execution events have no model, which is why the drawer for those metrics is
    empty rather than fabricated.
    """
    invalid = sorted(set(group_by) - _GROUP_BY_FIELDS)
    if invalid:
        raise HTTPException(
            status_code=422,
            detail=f"invalid group_by {invalid}; allowed: {sorted(_GROUP_BY_FIELDS)}",
        )
    if start_date and end_date and end_date <= start_date:
        raise HTTPException(status_code=422, detail="end_date must be after start_date")

    owner_id, agent_id = _scope_reads(auth, owner_id, agent_id)
    try:
        async with async_session() as session:
            # See the note in api_get_usage_events: one agent id, two columns.
            return await get_aggregated_usage(
                session, owner_id=owner_id, key_type=key_type, agent_id=agent_id,
                service_id=agent_id, operation=operation, label=label,
                model=model, provider=provider, phase=phase,
                start_date=start_date, end_date=end_date, group_by=group_by,
            )
    except Exception as e:
        logger.error(f"GET /v1/aggregate - Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An unexpected error occurred")


@router.get("/trend")
@track_time("API: Usage Trend")
async def api_get_usage_trend(
    owner_id: Optional[str] = Query(None, description="Defaults to your own email on a session"),
    key_type: Optional[str] = Query(None, description="platform-key | owner-key"),
    agent_id: Optional[str] = Query(None),
    operation: Optional[str] = Query(None),
    label: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    provider: Optional[str] = Query(None),
    phase: Optional[str] = Query(
        None, description="Checking | Preparing | Extracting | Answering"),
    days: int = Query(30, ge=1, le=366, description="Window length ending now"),
    bucket: str = Query("day", description="day | week | month"),
    auth: dict = Depends(get_api_key_or_session),
):
    """Usage over time — the Usage screen's trend chart.

    Buckets are ROLLING blocks ending now, not calendar days/weeks/months. A
    calendar-aligned final bucket is partial, and a partial bucket at the right edge of a
    line chart reads as a collapse in usage rather than as "the month isn't over yet".

    The series is DENSE and zero-filled: every bucket in the window comes back even when
    nothing happened in it, because a chart that skips empty buckets draws a straight line
    across the gap and implies usage that never occurred.

    Takes the same filters as `/v1/aggregate`, so the chart cannot disagree with the cards
    above it about which rows it describes. Each bucket carries `event_count` plus every
    metric summed, so one call serves the tokens, requests and cost views.
    """
    if bucket not in TREND_BUCKETS:
        raise HTTPException(
            status_code=422,
            detail=f"invalid bucket {bucket!r}; allowed: {sorted(TREND_BUCKETS)}",
        )

    owner_id, agent_id = _scope_reads(auth, owner_id, agent_id)
    try:
        async with async_session() as session:
            return await get_usage_trend(
                session, owner_id=owner_id, key_type=key_type, agent_id=agent_id,
                service_id=agent_id, operation=operation, label=label,
                model=model, provider=provider, phase=phase,
                days=days, bucket=bucket,
            )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error(f"GET /v1/trend - Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An unexpected error occurred")


@router.get("/summary/{owner_id}", response_model=UsageSummaryResponse)
@track_time("API: Usage Summary")
async def api_get_usage_summary(
    owner_id: str,
    start_date: Optional[datetime] = Query(None, description="ISO-8601, inclusive"),
    end_date: Optional[datetime] = Query(None, description="ISO-8601, exclusive"),
    auth: dict = Depends(get_api_key_or_session),
) -> UsageSummaryResponse:
    """One owner's usage broken down by service type and operation.

    `owner_id` is in the path, so "me" is accepted as a stand-in for the caller's own
    address — otherwise the dashboard would need to know its own email to build the URL.
    """
    if start_date and end_date and end_date <= start_date:
        raise HTTPException(status_code=422, detail="end_date must be after start_date")

    if owner_id == "me":
        resolved = auth.get("user_id")
        if not resolved:
            raise HTTPException(
                status_code=400,
                detail="owner_id 'me' needs a session; name the owner explicitly with an API key",
            )
        owner_id = resolved

    try:
        async with async_session() as session:
            return await get_usage_summary(
                session, owner_id=owner_id, start_date=start_date, end_date=end_date,
            )
    except Exception as e:
        logger.error(f"GET /v1/summary/{owner_id} - Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An unexpected error occurred")
