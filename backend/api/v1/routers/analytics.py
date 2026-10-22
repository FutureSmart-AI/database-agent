"""Agent Health & Analytics APIs.

Read-only aggregations over the local ``nl2sql_agent_health_events`` table, consumed by
the dashboard's Analytics screens. The chat flow writes the rows
(``agent.utils.agent_health_service``); these endpoints serve them — no event push, no
second database.

Ported from the orchestrator's ``routers/agent_health_router.py``, which owned this while
NL2SQL was one of its sub-services. Two deliberate differences now that NL2SQL is
standalone:

  * URLs are per-agent and RESTful (``/v1/agents/{agent_id}/analytics/...``), matching
    every other route in this service, so the dashboard's browser session reaches them
    directly instead of needing a master-key proxy.
  * Auth is this repo's ``get_api_key_or_session`` + ``require_agent_permission``, so a
    caller can only read the agents it may already use.

Endpoints:
  GET  /v1/agents/analytics/overview                     overview grid (all agents)
  GET  /v1/agents/{agent_id}/analytics/scorecard         full per-agent scorecard
  GET  /v1/agents/{agent_id}/analytics/failures          failure breakdown + top queries
  GET  /v1/agents/{agent_id}/analytics/trends            bucketed trend series + regression
  GET  /v1/agents/{agent_id}/analytics/queries           per-query drill-down (filter/sort)
  POST /v1/agents/{agent_id}/analytics/sync-costs        pull LangSmith cost/tokens
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from chatbot_management.utils.api_validation import get_api_key_or_session
from chatbot_management.services.logger import logger
from agent.utils.authorization import require_agent_permission
from chatbot_management.db_utils.agent_health_db_utils import (
    list_agents_overview,
    get_agent_scorecard,
    get_agent_failures,
    get_agent_trends,
    list_agent_queries,
    backfill_costs_from_langsmith,
    backfill_costs_by_run_id,
)

router = APIRouter(prefix="/v1", tags=["Analytics"])

_PERIODS = {"week", "month"}


def _require_period(period: str) -> None:
    if period not in _PERIODS:
        raise HTTPException(status_code=422, detail="period must be 'week' or 'month'")


def _custom_range(start_date: Optional[datetime], end_date: Optional[datetime]):
    """Validate an optional Custom Range (any dates). Both-or-neither; end after start.
    Returns ``(start, end)`` for the helper — both ``None`` means use the rolling
    ``period`` instead. Pass ISO-8601 dates/datetimes (e.g. ``2026-08-01`` or
    ``2026-08-01T00:00:00Z``)."""
    if (start_date is None) != (end_date is None):
        raise HTTPException(status_code=422, detail="provide both start_date and end_date, or neither")
    if start_date is not None and end_date is not None and end_date <= start_date:
        raise HTTPException(status_code=422, detail="end_date must be after start_date")
    return start_date, end_date


@router.get("/agents/analytics/overview")
async def analytics_overview(
    period: str = Query("week"),
    start_date: Optional[datetime] = Query(None, description="Custom range start (ISO-8601); with end_date overrides period"),
    end_date: Optional[datetime] = Query(None, description="Custom range end, exclusive (ISO-8601)"),
    sort: str = Query("total_queries"),
    order: str = Query("desc"),
    owner_id: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    auth: dict = Depends(get_api_key_or_session),
):
    """Overview grid: one flat row per agent for the window (queries, success, latency,
    tokens, cost). Pass start_date+end_date for a custom range, else period.

    Fleet-wide, so it carries no per-agent permission dependency: a session caller sees
    their own agents by passing `owner_id`, and the master key sees everything.
    """
    _require_period(period)
    start, end = _custom_range(start_date, end_date)
    if order not in {"asc", "desc"}:
        raise HTTPException(status_code=422, detail="order must be 'asc' or 'desc'")
    if sort not in {"success_rate", "total_queries", "total_cost", "avg_ms"}:
        raise HTTPException(
            status_code=422,
            detail="sort must be one of success_rate|total_queries|total_cost|avg_ms",
        )
    # A session caller is scoped to their own agents; only the master key sees the whole
    # fleet. `user_id` on a session is the caller's email, which is what health rows store
    # as owner_id (chat writes it from get_owner_email_by_agent_id).
    if auth.get("auth_type") == "session":
        owner_id = auth.get("user_id") or owner_id
    try:
        return await list_agents_overview(
            period=period, start=start, end=end, sort=sort, order=order,
            owner_id=owner_id, q=q, limit=limit, offset=offset,
        )
    except Exception as e:
        logger.error(f"GET /v1/agents/analytics/overview - Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An unexpected error occurred")


@router.get("/agents/{agent_id}/analytics/scorecard")
async def analytics_scorecard(
    agent_id: str = Path(..., description="Agent ID"),
    period: str = Query("week"),
    bucket: str = Query("day", description="usage.per_day granularity: hour | day | week | month"),
    start_date: Optional[datetime] = Query(None, description="Custom range start (ISO-8601); with end_date overrides period"),
    end_date: Optional[datetime] = Query(None, description="Custom range end, exclusive (ISO-8601)"),
    top_n: int = Query(10, ge=1, le=50),
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("use")),
):
    """Everything for one agent in one response: usage, quality (answered/failed),
    routing (SQL vs cross-DB vs pandas, and per-database), performance (latency incl.
    time inside the customer database), cost, tokens. Pass start_date+end_date for a
    custom range, else period. `bucket` sets the usage.per_day granularity (use hour for
    intraday time-of-day activity)."""
    _require_period(period)
    if bucket not in {"hour", "day", "week", "month"}:
        raise HTTPException(status_code=422, detail="bucket must be hour|day|week|month")
    start, end = _custom_range(start_date, end_date)
    try:
        data = await get_agent_scorecard(agent_id=agent_id, period=period, top_n=top_n,
                                         bucket=bucket, start=start, end=end)
        if data is None:
            raise HTTPException(status_code=404, detail=f"No analytics data for agent '{agent_id}'.")
        return data
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"GET /v1/agents/{agent_id}/analytics/scorecard - Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An unexpected error occurred")


@router.get("/agents/{agent_id}/analytics/failures")
async def analytics_failures(
    agent_id: str = Path(..., description="Agent ID"),
    period: str = Query("week"),
    start_date: Optional[datetime] = Query(None, description="Custom range start (ISO-8601); with end_date overrides period"),
    end_date: Optional[datetime] = Query(None, description="Custom range end, exclusive (ISO-8601)"),
    category: Optional[str] = Query(None, description="sql_error | db_connection | no_rows | sql_generation | out_of_scope | unanswered | exception"),
    failed_stage: Optional[str] = Query(None, description="Node the failure is attributed to: router | db_router | sql_gen | sql_exec | final_answer | chat_api"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("use")),
):
    """Failure category/stage/database breakdown + the most-repeated failed queries."""
    _require_period(period)
    start, end = _custom_range(start_date, end_date)
    try:
        data = await get_agent_failures(
            agent_id=agent_id, period=period, category=category,
            failed_stage=failed_stage, limit=limit, offset=offset, start=start, end=end,
        )
        if data is None:
            raise HTTPException(status_code=404, detail=f"No analytics data for agent '{agent_id}'.")
        return data
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"GET /v1/agents/{agent_id}/analytics/failures - Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An unexpected error occurred")


@router.get("/agents/{agent_id}/analytics/trends")
async def analytics_trends(
    agent_id: str = Path(..., description="Agent ID"),
    weeks: int = Query(8, ge=1, le=52),
    bucket: str = Query("week"),
    metrics: Optional[str] = Query(None, description="csv subset of success_rate,avg_ms,p95_ms,cost,failures,total_queries"),
    start_date: Optional[datetime] = Query(None, description="Custom range start (ISO-8601); with end_date overrides the trailing `weeks` window"),
    end_date: Optional[datetime] = Query(None, description="Custom range end, exclusive (ISO-8601)"),
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("use")),
):
    """Bucketed trend series + a server-side regression flag, plus the full
    current-vs-previous-period comparison for every headline metric. Pass
    start_date+end_date for a custom range (bucketed by `bucket`), else the trailing
    `weeks` window."""
    if bucket not in {"week", "day", "month"}:
        raise HTTPException(status_code=422, detail="bucket must be week|day|month")
    start, end = _custom_range(start_date, end_date)
    allowed = {"success_rate", "avg_ms", "p95_ms", "cost", "failures", "total_queries"}
    metrics_list = None
    if metrics:
        metrics_list = [m.strip() for m in metrics.split(",") if m.strip()]
        bad = [m for m in metrics_list if m not in allowed]
        if bad:
            raise HTTPException(status_code=422, detail=f"unknown metrics: {', '.join(bad)}")
    try:
        data = await get_agent_trends(
            agent_id=agent_id, weeks=weeks, bucket=bucket, metrics=metrics_list,
            start=start, end=end,
        )
        if data is None:
            raise HTTPException(status_code=404, detail=f"No analytics data for agent '{agent_id}'.")
        return data
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"GET /v1/agents/{agent_id}/analytics/trends - Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An unexpected error occurred")


@router.get("/agents/{agent_id}/analytics/queries")
async def analytics_queries(
    agent_id: str = Path(..., description="Agent ID"),
    period: str = Query("week"),
    sort: str = Query("latency_ms"),
    order: str = Query("desc"),
    status: Optional[str] = Query(None, description="answered | unanswered"),
    outcome: Optional[str] = Query(None, description="success | failure"),
    failure_category: Optional[str] = Query(None),
    failed_stage: Optional[str] = Query(None),
    route: Optional[str] = Query(None, description="sql | cross_db | pandas | direct_answer"),
    model: Optional[str] = Query(None),
    db_id: Optional[str] = Query(None, description="Only queries routed to this database"),
    min_tokens: Optional[int] = Query(None, ge=0),
    min_cost_usd: Optional[float] = Query(None, ge=0),
    min_latency_ms: Optional[int] = Query(None, ge=0),
    chat_id: Optional[str] = Query(None),
    feedback: Optional[str] = Query(None, description="Filter by user feedback: positive | negative | none (unrated) | any (rated)"),
    include_node_data: bool = Query(True, description="Include the per-node breakdown (metrics.node_data) in each row; set false for a lean list"),
    start_date: Optional[datetime] = Query(None, description="Custom range start (ISO-8601); with end_date overrides period (ignored when chat_id is set)"),
    end_date: Optional[datetime] = Query(None, description="Custom range end, exclusive (ISO-8601)"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("use")),
):
    """Per-query drill-down — slowest / most-expensive / failure investigation, each row
    carrying the SQL it ran, the database it used and its per-node spend. Pass
    start_date+end_date for a custom range, else period (both ignored when chat_id is
    set)."""
    if not chat_id:
        _require_period(period)
    start, end = _custom_range(start_date, end_date)
    if sort not in {"latency_ms", "cost_usd", "total_tokens", "retry_count", "created_at"}:
        raise HTTPException(
            status_code=422,
            detail="sort must be one of latency_ms|cost_usd|total_tokens|retry_count|created_at",
        )
    if order not in {"asc", "desc"}:
        raise HTTPException(status_code=422, detail="order must be 'asc' or 'desc'")
    if outcome is not None and outcome not in {"success", "failure"}:
        raise HTTPException(status_code=422, detail="outcome must be success|failure")
    if feedback is not None and feedback.strip().lower() not in {"positive", "negative", "none", "unrated", "any", "rated"}:
        raise HTTPException(status_code=422, detail="feedback must be positive|negative|none|any")
    try:
        data = await list_agent_queries(
            agent_id=agent_id, period=period, sort=sort, order=order, status=status,
            outcome=outcome, failure_category=failure_category, failed_stage=failed_stage,
            route=route, model=model, db_id=db_id,
            min_tokens=min_tokens, min_cost_usd=min_cost_usd,
            min_latency_ms=min_latency_ms, chat_id=chat_id, feedback=feedback,
            include_node_data=include_node_data, start=start, end=end,
            limit=limit, offset=offset,
        )
        if data is None:
            raise HTTPException(status_code=404, detail=f"No analytics data for agent '{agent_id}'.")
        return data
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"GET /v1/agents/{agent_id}/analytics/queries - Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An unexpected error occurred")


@router.post("/agents/{agent_id}/analytics/sync-costs")
async def analytics_sync_costs(
    agent_id: str = Path(..., description="Agent ID"),
    period: str = Query("week"),
    strategy: str = Query("run_id", description="run_id (direct read_run per row) | metadata (agent_id/chat_id rollup) | both"),
    start_date: Optional[datetime] = Query(None, description="Custom range start (ISO-8601); with end_date overrides period"),
    end_date: Optional[datetime] = Query(None, description="Custom range end, exclusive (ISO-8601)"),
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("use")),
):
    """Pull LangSmith-priced cost AND token counts for the agent's window and write them
    into nl2sql_agent_health_events (LangSmith is the source of truth for cost). The read
    endpoints then serve these values. Sync the SAME window you'll read.

    Each query already schedules its own pricing pass a few seconds after it answers, so
    this is the backstop — for rows whose finalizer was lost to a restart, whose trace was
    priced late, or that predate the feature.

    strategy:
      - "run_id" (default): direct read_run per row on the stored langsmith_run_id — no
        project / metadata-filter dependency; covers only rows that captured a run id.
      - "metadata": one server-side query for the agent's root runs, matched to rows by
        chat_id metadata. Requires LANGCHAIN_PROJECT.
      - "both": run_id first, then metadata for anything still incomplete.

    Returns the backfill summary (or both summaries)."""
    _require_period(period)
    if strategy not in ("metadata", "run_id", "both"):
        raise HTTPException(status_code=422, detail="strategy must be one of: metadata, run_id, both")
    start, end = _custom_range(start_date, end_date)
    try:
        if strategy == "metadata":
            return await backfill_costs_from_langsmith(agent_id=agent_id, period=period, start=start, end=end)
        if strategy == "both":
            by_run = await backfill_costs_by_run_id(agent_id=agent_id, period=period, start=start, end=end)
            meta = await backfill_costs_from_langsmith(agent_id=agent_id, period=period, start=start, end=end)
            return {"strategy": "both", "run_id": by_run, "metadata": meta}
        return await backfill_costs_by_run_id(agent_id=agent_id, period=period, start=start, end=end)
    except Exception as e:
        logger.error(f"POST /v1/agents/{agent_id}/analytics/sync-costs - Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An unexpected error occurred")
