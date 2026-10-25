"""Agent Health — local persistence + read aggregations.

This is the storage + query layer behind the Agent Health analytics APIs
(``api/v1/routers/analytics.py``). The chat flow writes ONE row per query here
(``insert_agent_health_event``, called from ``agent.utils.agent_health_service.send_query_event``);
the dashboard PULLS aggregates via the read helpers below — no event push, no second
database.

Ported from the orchestrator's ``chat_utils/db/agent_health_events.py``, which owned this
data while NL2SQL was one of its sub-services. NL2SQL now runs standalone, so it owns its
own table (``nl2sql_agent_health_events``) and the same aggregations, minus the
sub-service stitching the parent needed: here every row IS this service's own spend, so
the LangSmith backfills price every row instead of skipping some.

Conventions follow the rest of this repo: async SQLModel sessions, half-open
``[since, until)`` windows over naive-UTC datetimes, ``@track_time`` instrumentation.
``cost_usd`` is summed only over priced rows (``FILTER (WHERE cost_usd IS NOT NULL)``) and
``cost_complete`` is the AND of the window's per-row flags — unpriced spend is never
counted as 0.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import case, func, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import and_, select

from logger import logger
from models.sql_models import AgentHealthEvent, ChatLogs
from chatbot_management.services.sqlmodel_session import async_session
from otel_tracing import track_time

# ── Status buckets ───────────────────────────────────────────────────────────
# Status is BINARY ("answered" / "no_answer"), plus "error" for a run that blew up
# before it could answer. Headline success_rate uses is_answered, not these buckets.
SUCCESS_STATUSES = ("answered",)
FAILURE_STATUSES = ("no_answer", "error")
EXCLUDED_STATUSES = ()  # nothing is excluded from NL2SQL's rate today; kept for shape parity

# NL2SQL routes, as classified by agent_health_service.
ROUTES = ("sql", "cross_db", "pandas", "direct_answer")


# ── small helpers ────────────────────────────────────────────────────────────
def _to_naive_utc(dt: datetime) -> datetime:
    """Compare against DB datetimes stored as naive UTC."""
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _to_utc_z(dt: Optional[datetime]) -> Optional[str]:
    if not isinstance(dt, datetime):
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_event_ts(ts: Any) -> datetime:
    """Parse the emitted ISO-8601 ``...Z`` timestamp into a naive-UTC datetime."""
    if isinstance(ts, datetime):
        return _to_naive_utc(ts)
    if isinstance(ts, str) and ts.strip():
        try:
            return _to_naive_utc(datetime.fromisoformat(ts.strip().replace("Z", "+00:00")))
        except Exception:
            pass
    return datetime.utcnow()


def _window(period: str) -> Tuple[datetime, datetime]:
    """Half-open ``[since, until)`` for ``week`` (7d) / ``month`` (~30d)."""
    until = datetime.utcnow()
    since = until - timedelta(days=30 if period == "month" else 7)
    return since, until


def _resolve_window(
    period: str, start: Optional[datetime] = None, end: Optional[datetime] = None
) -> Tuple[datetime, datetime]:
    """Resolve the query window: an explicit half-open ``[start, end)`` (any dates,
    e.g. the dashboard's Custom Range) when BOTH are given, else the rolling
    ``period`` (week/month). Stored datetimes are naive-UTC, so we normalize."""
    if start is not None and end is not None:
        return _to_naive_utc(start), _to_naive_utc(end)
    return _window(period)


def _safe_rate(num: int, den: int) -> float:
    return round((num / den) * 100, 1) if den else 0.0


def _cmp(cur, prev) -> Dict[str, Any]:
    """Current vs previous period: {current, previous, delta, pct_change}.
    ``delta`` is current-minus-previous (absolute); ``pct_change`` is the % change
    relative to previous (None when previous is 0). For rates (success_rate,
    positive_rate) ``delta`` is in percentage POINTS."""
    c = round(cur, 6) if isinstance(cur, float) else cur
    p = round(prev, 6) if isinstance(prev, float) else prev
    delta = c - p
    if isinstance(delta, float):
        delta = round(delta, 6)
    pct = round((delta / p) * 100, 1) if p else None
    return {"current": c, "previous": p, "delta": delta, "pct_change": pct}


def _positive_rate(fb: Dict[str, int]) -> float:
    t = (fb.get("positive") or 0) + (fb.get("negative") or 0)
    return round((fb.get("positive") or 0) / t * 100, 1) if t else 0.0


# ── WRITE ────────────────────────────────────────────────────────────────────
@track_time("DB: Agent Health - insert event")
async def insert_agent_health_event(event: Dict[str, Any]) -> bool:
    """Persist one health event (one row per query). Idempotent on ``chat_id``."""
    chat_id = event.get("chat_id")
    if not chat_id:
        logger.warning("[agent_health] event missing chat_id — skipping insert")
        return False
    m = event.get("metrics") or {}
    row = AgentHealthEvent(
        event_type=event.get("event_type", "agent_query"),
        schema_version=int(event.get("schema_version", 1) or 1),
        event_ts=_parse_event_ts(event.get("timestamp")),
        agent_id=event.get("agent_id"),
        owner_id=event.get("owner_id"),
        user_id=event.get("user_id"),
        session_id=event.get("session_id"),
        chat_id=chat_id,
        request_id=event.get("request_id"),
        trace_id=event.get("trace_id"),
        langsmith_run_id=event.get("langsmith_run_id"),
        query=event.get("query") or "",
        refined_query=event.get("refined_query"),
        route=event.get("route"),
        nodes_used=list(event.get("nodes_used") or []),
        db_id=event.get("db_id"),
        db_ids=list(event.get("db_ids") or []),
        cross_db=bool(event.get("cross_db")),
        sql_query=event.get("sql_query"),
        selected_tables=list(event.get("selected_tables") or []),
        rows_returned=event.get("rows_returned"),
        chart_generated=bool(event.get("chart_generated")),
        pandas_used=bool(event.get("pandas_used")),
        status=event.get("status"),
        is_answered=bool(event.get("is_answered")),
        failure_category=event.get("failure_category"),
        failed_stage=event.get("failed_stage"),
        failure_detail=event.get("failure_detail") or None,
        from_widget=bool(event.get("from_widget")),
        key_type=event.get("key_type"),
        provider=event.get("provider"),
        model=event.get("model"),
        latency_ms=int(m.get("latency_ms") or 0),
        db_fetch_ms=int(m.get("db_fetch_ms") or 0),
        sql_exec_ms=int(m.get("sql_exec_ms") or 0),
        input_tokens=int(m.get("input_tokens") or 0),
        output_tokens=int(m.get("output_tokens") or 0),
        total_tokens=int(m.get("total_tokens") or 0),
        cost_usd=m.get("cost_usd"),  # keep None when unpriced — never coerce to 0
        cost_complete=bool(m.get("cost_complete", False)),
        retry_count=int(m.get("retry_count") or 0),
        node_data=event.get("node_data") or [],
    )
    try:
        async with async_session() as session:
            session.add(row)
            await session.commit()
        logger.info(
            "[agent_health] stored event agent=%s status=%s route=%s cost_complete=%s",
            row.agent_id, row.status, row.route, row.cost_complete,
        )
        return True
    except IntegrityError:
        logger.info("[agent_health] duplicate chat_id %s — idempotent skip", chat_id)
        return True
    except Exception as e:  # never raise from monitoring
        logger.error("[agent_health] insert failed: %s", e, exc_info=True)
        return False


async def update_row_usage_from_langsmith(
    chat_id: str, usage: Dict[str, Any], cost_complete: Optional[bool] = None,
) -> bool:
    """Write ONE row's tokens + cost from a LangSmith usage result.

    Used by the per-query auto-finalizer (``agent_health_service.finalize_query_cost``)
    so accurate LangSmith cost/tokens land on the row without a manual sync. Tokens are
    written whenever present; ``cost_usd`` only when present. ``cost_complete`` defaults
    to True when a cost is written, but the caller can pass False for a PARTIAL total so
    the dashboard still flags it as a lower bound. Idempotent; returns True iff a row was
    updated."""
    if not chat_id or not usage:
        return False
    try:
        vals: Dict[str, Any] = {}
        it, ot = usage.get("input_tokens"), usage.get("output_tokens")
        if it is not None or ot is not None:
            it, ot = int(it or 0), int(ot or 0)
            vals.update(input_tokens=it, output_tokens=ot, total_tokens=it + ot)
        c = usage.get("cost_usd")
        if c is not None:
            vals.update(cost_usd=float(c),
                        cost_complete=(bool(cost_complete) if cost_complete is not None else True))
        if not vals:
            return False
        async with async_session() as session:
            res = await session.execute(
                update(AgentHealthEvent).where(AgentHealthEvent.chat_id == chat_id).values(**vals)
            )
            await session.commit()
        return bool(res.rowcount)
    except Exception as e:  # never raise from monitoring
        logger.error("[agent_health] update_row_usage_from_langsmith error: %s", e, exc_info=True)
        return False


async def update_row_node_data(chat_id: str, node_data: list) -> bool:
    """MERGE a per-node breakdown into the row's ``node_data``, keyed by ``node_name``.

    The row already carries the locally-captured breakdown (tokens, latency, calls,
    errors) written at insert time. The finalizer then supplies LangSmith's priced view,
    which knows cost but not our node latencies — so this merges field-by-field instead of
    replacing, and a node LangSmith doesn't recognise keeps its local numbers. Nodes only
    LangSmith saw (db_router, which has no local token capture) are appended.

    Idempotent; never raises."""
    if not chat_id or not node_data:
        return False
    try:
        async with async_session() as session:
            existing = (await session.execute(
                select(_E.node_data).where(_E.chat_id == chat_id)
            )).scalar_one_or_none()
            merged: List[Dict[str, Any]] = [dict(n) for n in (existing or []) if isinstance(n, dict)]
            by_name = {n.get("node_name"): n for n in merged}
            for incoming in node_data:
                if not isinstance(incoming, dict):
                    continue
                target = by_name.get(incoming.get("node_name"))
                if target is None:
                    merged.append(dict(incoming))
                    by_name[incoming.get("node_name")] = merged[-1]
                    continue
                # Only overwrite with values LangSmith actually reported — a missing or
                # zero field must not wipe the local capture.
                for key, value in incoming.items():
                    if value not in (None, 0, 0.0, "", []):
                        target[key] = value
            res = await session.execute(
                update(AgentHealthEvent).where(AgentHealthEvent.chat_id == chat_id)
                .values(node_data=merged)
            )
            await session.commit()
        return bool(res.rowcount)
    except Exception as e:  # never raise from monitoring
        logger.error("[agent_health] update_row_node_data error: %s", e, exc_info=True)
        return False


@track_time("DB: Agent Health - backfill costs from LangSmith")
async def backfill_costs_from_langsmith(
    agent_id: str, period: str = "week",
    start: Optional[datetime] = None, end: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Pull LangSmith-priced cost AND token counts for this agent's window and write them
    into ``nl2sql_agent_health_events`` (``cost_usd``/``cost_complete`` and
    ``input_tokens``/``output_tokens``/``total_tokens``), keyed by ``chat_id`` — so the
    read APIs serve LangSmith as the source of truth for BOTH spend and tokens instead of
    the local token accounting. Idempotent (re-running re-writes the same values).
    Returns a summary; never raises.

    Tokens are written as soon as LangSmith reports them, even before the run is priced
    (LangSmith prices asynchronously); cost + ``cost_complete=True`` are set only once the
    run is priced.

    SCOPE — ``fetch_agent_costs`` rolls up this service's root ``NL2SQL LangGraph`` run,
    which covers every in-graph LLM call: router, db_router, sql_gen, final_answer, the
    pandas agent and the chart agent all run inside it. Unlike the orchestrator's version
    there is no sub-service to skip — NL2SQL is the leaf."""
    import asyncio
    from agent.utils.langsmith_cost import fetch_agent_costs

    since, until = _resolve_window(period, start, end)
    costs = await asyncio.to_thread(fetch_agent_costs, agent_id, since, until)

    updated = 0
    total = 0.0
    async with async_session() as session:
        for chat_id, info in costs.items():
            vals: Dict[str, Any] = {}
            it, ot = info.get("input_tokens"), info.get("output_tokens")
            if it is not None or ot is not None:
                it, ot = int(it or 0), int(ot or 0)
                vals.update(input_tokens=it, output_tokens=ot, total_tokens=it + ot)
            c = info.get("cost_usd")
            if c is not None:  # priced → set cost and mark the row complete
                vals.update(cost_usd=float(c), cost_complete=True)
                total += float(c)
            if not vals:
                continue  # LangSmith has neither tokens nor cost yet — leave the row as-is
            res = await session.execute(
                update(AgentHealthEvent)
                .where(AgentHealthEvent.chat_id == chat_id)
                .values(**vals)
            )
            updated += res.rowcount or 0
        await session.commit()

    logger.info(
        "[agent_health] LangSmith backfill agent=%s period=%s runs=%d updated=%d total=$%.4f",
        agent_id, period, len(costs), updated, total,
    )
    return {
        "agent_id": agent_id, "period": period, "source": "langsmith",
        "runs_found": len(costs), "rows_updated": updated, "total_cost": round(total, 6),
    }


@track_time("DB: Agent Health - backfill costs by run id")
async def backfill_costs_by_run_id(
    agent_id: str, period: str = "week",
    start: Optional[datetime] = None, end: Optional[datetime] = None,
    only_incomplete: bool = True,
) -> Dict[str, Any]:
    """Price rows by a DIRECT LangSmith ``read_run`` on the stored ``langsmith_run_id``.

    An alternative to :func:`backfill_costs_from_langsmith` that does NOT depend on the
    agent_id/chat_id metadata filter or ``LANGCHAIN_PROJECT`` — it reads each row's own
    captured root run id. Writes tokens as soon as LangSmith reports them and cost +
    ``cost_complete=True`` once the run is priced. Idempotent; never raises.

    Rows without a ``langsmith_run_id`` (created before the column shipped, or with
    LangSmith inactive) are skipped — use :func:`backfill_costs_from_langsmith` for those.

    ``only_incomplete`` (default True) limits work to rows still missing a complete cost;
    pass False to re-price every priced-or-not row in the window."""
    import asyncio
    from agent.utils.langsmith_cost import fetch_run_usage

    since, until = _resolve_window(period, start, end)
    conds = [_E.agent_id == agent_id, _E.event_ts >= since, _E.event_ts < until,
             _E.langsmith_run_id.isnot(None)]
    if only_incomplete:
        conds.append(_E.cost_complete.is_(False))

    # 1. Collect candidate rows (short read-only session — no network held open).
    async with async_session() as session:
        rows = (await session.execute(
            select(_E.chat_id, _E.langsmith_run_id).where(and_(*conds))
        )).all()

    candidates = [(r.chat_id, r.langsmith_run_id) for r in rows]
    if not candidates:
        logger.info("[agent_health] run-id backfill agent=%s: no candidate rows", agent_id)
        return {
            "agent_id": agent_id, "period": period, "source": "langsmith_run_id",
            "candidates": 0, "rows_updated": 0, "rows_fetch_failed": 0, "total_cost": 0.0,
        }

    # 2. Read each run from LangSmith with BOUNDED concurrency. asyncio.to_thread uses the
    # loop's shared default executor, so an unbounded gather over a large window could both
    # monopolize that pool app-wide and hammer the LangSmith API.
    sem = asyncio.Semaphore(8)

    async def _read(run_id: str) -> Dict[str, Any]:
        async with sem:
            try:
                return await asyncio.to_thread(fetch_run_usage, run_id)
            except Exception:  # fetch_run_usage already guards; stay safe regardless
                return {}

    usages = await asyncio.gather(*[_read(rid) for (_cid, rid) in candidates])

    # 3. Write tokens / cost back.
    updated = 0
    total = 0.0
    fetch_failed = 0
    async with async_session() as session:
        for (chat_id, _rid), usage in zip(candidates, usages):
            if not usage:
                fetch_failed += 1  # read returned nothing (failure or run not found)
                continue
            vals: Dict[str, Any] = {}
            it, ot = usage.get("input_tokens"), usage.get("output_tokens")
            if it is not None or ot is not None:
                it, ot = int(it or 0), int(ot or 0)
                vals.update(input_tokens=it, output_tokens=ot, total_tokens=it + ot)
            c = usage.get("cost_usd")
            if c is not None:  # priced → set cost and mark the row complete
                vals.update(cost_usd=float(c), cost_complete=True)
                total += float(c)
            if not vals:
                continue  # run exists but reported neither tokens nor cost — leave as-is
            res = await session.execute(
                update(AgentHealthEvent)
                .where(AgentHealthEvent.chat_id == chat_id)
                .values(**vals)
            )
            updated += res.rowcount or 0
        await session.commit()

    # Surface a high read-failure rate — otherwise a silent run "succeeds" while leaving
    # most rows unpriced (expired key / rate limit / wrong workspace).
    if fetch_failed > len(candidates) * 0.1:
        logger.warning(
            "[agent_health] run-id backfill agent=%s: %d/%d LangSmith reads returned nothing "
            "(check LANGCHAIN_API_KEY / workspace / run ids)",
            agent_id, fetch_failed, len(candidates),
        )
    logger.info(
        "[agent_health] LangSmith run-id backfill agent=%s period=%s candidates=%d updated=%d fetch_failed=%d total=$%.4f",
        agent_id, period, len(candidates), updated, fetch_failed, total,
    )
    return {
        "agent_id": agent_id, "period": period, "source": "langsmith_run_id",
        "candidates": len(candidates), "rows_updated": updated,
        "rows_fetch_failed": fetch_failed, "total_cost": round(total, 6),
    }


# ── shared aggregate expressions ─────────────────────────────────────────────
_E = AgentHealthEvent
_sum_answered = func.sum(case((_E.is_answered.is_(True), 1), else_=0))   # Answered (is_answered=true)
_sum_success = func.sum(case((_E.status.in_(SUCCESS_STATUSES), 1), else_=0))
_sum_failed = func.sum(case((_E.status.in_(FAILURE_STATUSES), 1), else_=0))
_sum_error = func.sum(case((_E.status == "error", 1), else_=0))          # Failed API requests
_p95 = func.percentile_cont(0.95).within_group(_E.latency_ms.asc())
_cost_sum = func.sum(_E.cost_usd).filter(_E.cost_usd.isnot(None))


async def _agent_seen(session, agent_id: str) -> bool:
    """True if this agent has EVER produced a health event (any window).

    Used to return 404 ``agent_not_found`` for unknown agents on the read routes, vs.
    200-with-empty for a known agent that simply had no rows in the window.
    """
    return bool((await session.execute(
        select(func.count()).where(_E.agent_id == agent_id)
    )).scalar())


# ── READ §2: overview grid ───────────────────────────────────────────────────
@track_time("DB: Agent Health - agents overview")
async def list_agents_overview(
    *, period: str = "week", start: Optional[datetime] = None, end: Optional[datetime] = None,
    sort: str = "total_queries", order: str = "desc",
    owner_id: Optional[str] = None, q: Optional[str] = None,
    limit: int = 50, offset: int = 0,
) -> Dict[str, Any]:
    """One flat row per agent for the window — the basics only:
    queries, users, success rate, latency, tokens, cost."""
    since, until = _resolve_window(period, start, end)
    conds = [_E.event_ts >= since, _E.event_ts < until]
    if owner_id:
        conds.append(_E.owner_id == owner_id)

    async with async_session() as session:
        rows = (await session.execute(
            select(
                _E.agent_id, _E.owner_id,
                func.count().label("total"),
                _sum_answered.label("answered"),
                _sum_error.label("errors"),
                func.count(func.distinct(_E.user_id)).label("uniq"),
                func.avg(_E.latency_ms).label("avg_ms"),
                _p95.label("p95"),
                func.sum(_E.total_tokens).label("tokens"),
                _cost_sum.label("cost"),
                func.bool_and(_E.cost_complete).label("cost_complete"),
            ).where(and_(*conds)).group_by(_E.agent_id, _E.owner_id)
        )).all()

        # Leading failure category per agent.
        fc = (await session.execute(
            select(_E.agent_id, _E.failure_category, func.count().label("c"))
            .where(and_(*conds, _E.failure_category.isnot(None)))
            .group_by(_E.agent_id, _E.failure_category)
        )).all()
        top_fc: Dict[str, Tuple[str, int]] = {}
        for r in fc:
            cur = top_fc.get(r.agent_id)
            if cur is None or (r.c or 0) > cur[1]:
                top_fc[r.agent_id] = (r.failure_category, int(r.c or 0))

    agents: List[Dict[str, Any]] = []
    tot_q = 0
    tot_cost = 0.0
    cost_all_complete = True
    for r in rows:
        total = int(r.total or 0)
        answered = int(r.answered or 0)
        # Success Rate = Answered / Total (matches the dashboard's definition).
        success_rate = _safe_rate(answered, total)
        cost_complete = bool(r.cost_complete) if r.cost_complete is not None else True
        if not cost_complete:
            cost_all_complete = False
        tot_q += total
        tot_cost += float(r.cost or 0)
        agents.append({
            "agent_id": r.agent_id, "owner_id": r.owner_id,
            "name": None,  # filled by the router from chatbot_details
            "total_queries": total, "unique_users": int(r.uniq or 0),
            "answered": answered, "unanswered": total - answered,
            "success_rate": success_rate,
            "failed_api_requests": int(r.errors or 0),
            "avg_ms": int(r.avg_ms) if r.avg_ms is not None else 0,
            "p95_ms": int(r.p95) if r.p95 is not None else None,
            "total_tokens": int(r.tokens or 0),
            "total_cost": round(float(r.cost or 0), 6),
            "avg_cost_per_query": round(float(r.cost or 0) / total, 6) if total else 0.0,
            "cost_complete": cost_complete,
            "top_failure_category": top_fc.get(r.agent_id, (None, 0))[0],
        })

    if q:
        ql = q.lower()
        agents = [x for x in agents if ql in (x["agent_id"] or "").lower()]

    sort_key = {
        "success_rate": lambda x: x["success_rate"],
        "total_queries": lambda x: x["total_queries"],
        "total_cost": lambda x: x["total_cost"],
        "avg_ms": lambda x: x["avg_ms"],
    }.get(sort, lambda x: x["total_queries"])
    agents.sort(key=sort_key, reverse=(order == "desc"))
    total_agents = len(agents)
    page = agents[offset: offset + limit]

    return {
        "period": period, "since": _to_utc_z(since), "until": _to_utc_z(until),
        "sort": sort, "order": order, "total_agents": total_agents,
        "limit": limit, "offset": offset,
        "summary": {"total_queries": tot_q, "total_cost": round(tot_cost, 6),
                    "cost_complete": cost_all_complete},
        "agents": page,
    }


# ── READ §3: per-agent scorecard ─────────────────────────────────────────────
async def _window_aggregates(session, agent_id: str, since: datetime, until: datetime) -> Dict[str, Any]:
    conds = [_E.agent_id == agent_id, _E.event_ts >= since, _E.event_ts < until]
    r = (await session.execute(
        select(
            func.count().label("total"),
            _sum_answered.label("answered"),
            func.count(func.distinct(_E.user_id)).label("uniq"),
            func.sum(case((_E.from_widget.is_(True), 1), else_=0)).label("widget"),
            _sum_success.label("success"), _sum_failed.label("failed"),
            _sum_error.label("errors"),
            func.sum(case((_E.status == "no_answer", 1), else_=0)).label("no_answer"),
            func.avg(_E.latency_ms).label("avg_ms"),
            func.percentile_cont(0.5).within_group(_E.latency_ms.asc()).label("p50"),
            _p95.label("p95"),
            # NL2SQL-specific: how much of the wall clock was the customer's database,
            # and how many queries took each route.
            func.avg(_E.sql_exec_ms).label("avg_sql_ms"),
            func.sum(case((_E.cross_db.is_(True), 1), else_=0)).label("cross_db"),
            func.sum(case((_E.pandas_used.is_(True), 1), else_=0)).label("pandas"),
            func.sum(case((_E.chart_generated.is_(True), 1), else_=0)).label("charts"),
            func.sum(_E.retry_count).label("retries"),
            _cost_sum.label("cost"),
            func.sum(_E.total_tokens).label("tokens"),
            func.sum(_E.input_tokens).label("in_tok"),
            func.sum(_E.output_tokens).label("out_tok"),
            func.bool_and(_E.cost_complete).label("cost_complete"),
        ).where(and_(*conds))
    )).one()
    total = int(r.total or 0)
    answered = int(r.answered or 0)
    return {
        "total": total, "answered": answered, "unanswered": total - answered,
        "uniq": int(r.uniq or 0), "widget": int(r.widget or 0),
        "success": int(r.success or 0), "failed": int(r.failed or 0),
        "errors": int(r.errors or 0), "no_answer": int(r.no_answer or 0),
        "avg_ms": int(r.avg_ms) if r.avg_ms is not None else 0,
        "p50": int(r.p50) if r.p50 is not None else 0,
        "p95": int(r.p95) if r.p95 is not None else 0,
        "avg_sql_ms": int(r.avg_sql_ms) if r.avg_sql_ms is not None else 0,
        "cross_db": int(r.cross_db or 0), "pandas": int(r.pandas or 0),
        "charts": int(r.charts or 0), "retries": int(r.retries or 0),
        "cost": round(float(r.cost or 0), 6),
        "tokens": int(r.tokens or 0),
        "input_tokens": int(r.in_tok or 0), "output_tokens": int(r.out_tok or 0),
        "cost_complete": bool(r.cost_complete) if r.cost_complete is not None else True,
        # Success Rate = Answered / Total (matches the dashboard's definition).
        "success_rate": _safe_rate(answered, total),
    }


async def _node_agg(session, agent_id: str, since: datetime, until: datetime) -> Dict[str, Dict[str, Any]]:
    """Aggregate per-NODE cost/tokens/latency across the window, from each row's
    ``node_data`` JSON. Returns ``{node_name: {..sums.., queries}}``. Used by the
    scorecard for the node-level breakdown (perf + cost)."""
    rows = (await session.execute(
        select(_E.node_data).where(
            _E.agent_id == agent_id, _E.event_ts >= since, _E.event_ts < until,
            _E.node_data.isnot(None),
        )
    )).scalars().all()
    agg: Dict[str, Dict[str, Any]] = {}
    for nd in rows:
        if not isinstance(nd, list):
            continue
        for n in nd:
            if not isinstance(n, dict):
                continue
            name = n.get("node_name") or "other"
            a = agg.setdefault(name, {
                "node_name": name, "model": n.get("model"), "provider": n.get("provider"),
                "queries": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
                "input_cost": 0.0, "output_cost": 0.0, "total_cost": 0.0,
                "latency_ms": 0, "latencies": [], "calls": 0, "errors": 0,
            })
            a["queries"] += 1
            a["input_tokens"] += int(n.get("input_tokens") or 0)
            a["output_tokens"] += int(n.get("output_tokens") or 0)
            a["total_tokens"] += int(n.get("total_tokens") or 0)
            a["input_cost"] += float(n.get("input_cost") or 0)
            a["output_cost"] += float(n.get("output_cost") or 0)
            a["total_cost"] += float(n.get("total_cost") or 0)
            _lat = int(n.get("latency_ms") or 0)
            a["latency_ms"] += _lat
            a["latencies"].append(_lat)                # for p50 / p95 across queries
            a["calls"] += int(n.get("calls") or 1)     # total LLM calls in this node
            a["errors"] += int(n.get("errors") or 0)
            if not a.get("model"):
                a["model"] = n.get("model")
            if not a.get("provider"):
                a["provider"] = n.get("provider")
    return agg


def _pct(vals: List[int], p: int) -> int:
    """Nearest-rank percentile of a list (0 when empty)."""
    if not vals:
        return 0
    s = sorted(vals)
    k = max(0, min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1)))))
    return int(s[k])


def _build_by_node(cur_nodes: Dict[str, Dict]) -> List[Dict[str, Any]]:
    """Per-node breakdown (CURRENT window): latency (avg/p50/p95, ms + seconds),
    calls, errors, tokens, cost. Previous-period comparison lives in /trends."""
    out: List[Dict[str, Any]] = []
    for name, a in cur_nodes.items():
        lats = a.get("latencies") or []
        avg_ms = int(sum(lats) / len(lats)) if lats else 0
        p50_ms, p95_ms = _pct(lats, 50), _pct(lats, 95)
        out.append({
            "node_name": name, "model": a.get("model"), "provider": a.get("provider"),
            "queries": a["queries"], "total_calls": int(a.get("calls") or a["queries"]),
            "errors": int(a.get("errors") or 0),
            # latency — both ms and seconds (UI shows seconds)
            "avg_latency_ms": avg_ms, "p50_latency_ms": p50_ms, "p95_latency_ms": p95_ms,
            "avg_latency_s": round(avg_ms / 1000, 2),
            "p50_latency_s": round(p50_ms / 1000, 2),
            "p95_latency_s": round(p95_ms / 1000, 2),
            "total_latency_ms": a["latency_ms"],
            # tokens + cost
            "total_tokens": a["total_tokens"],
            "input_tokens": a["input_tokens"], "output_tokens": a["output_tokens"],
            "total_cost": round(a["total_cost"], 6),
            "input_cost": round(a["input_cost"], 6), "output_cost": round(a["output_cost"], 6),
        })
    out.sort(key=lambda x: (x["total_cost"], x["total_latency_ms"]), reverse=True)
    return out


async def _feedback_counts(session, agent_id: str, since: datetime, until: datetime) -> Dict[str, int]:
    """{"positive", "negative"} feedback counts for the window (from nl2sql_logs)."""
    rows = (await session.execute(
        select(ChatLogs.feedback, func.count().label("c")).where(
            ChatLogs.chat_id.in_(select(_E.chat_id).where(
                _E.agent_id == agent_id, _E.event_ts >= since, _E.event_ts < until)),
            ChatLogs.feedback.isnot(None),
        ).group_by(ChatLogs.feedback)
    )).all()
    fb = {"positive": 0, "negative": 0}
    for r in rows:
        if r.feedback in fb:
            fb[r.feedback] = int(r.c or 0)
    return fb


async def _period_comparison(session, agent_id: str, since: datetime, until: datetime) -> Dict[str, Any]:
    """Current-vs-previous-period comparison for every headline metric, each as
    ``{current, previous, delta, pct_change}`` (delta for rates is in pp). The previous
    window is the equal-length span immediately before ``since``. Served by /trends so
    the scorecard stays current-state only."""
    prev_since = since - (until - since)
    cur = await _window_aggregates(session, agent_id, since, until)
    prev = await _window_aggregates(session, agent_id, prev_since, since)
    fb_cur = await _feedback_counts(session, agent_id, since, until)
    fb_prev = await _feedback_counts(session, agent_id, prev_since, since)
    ac = round(cur["cost"] / cur["total"], 6) if cur["total"] else 0.0
    ap = round(prev["cost"] / prev["total"], 6) if prev["total"] else 0.0
    return {
        "previous_since": _to_utc_z(prev_since),
        "total_queries": _cmp(cur["total"], prev["total"]),
        "answered": _cmp(cur["answered"], prev["answered"]),
        "unanswered": _cmp(cur["unanswered"], prev["unanswered"]),
        "success_rate": _cmp(cur["success_rate"], prev["success_rate"]),   # delta in pp
        "failed_api_requests": _cmp(cur["errors"], prev["errors"]),
        "avg_ms": _cmp(cur["avg_ms"], prev["avg_ms"]),
        "avg_s": _cmp(round(cur["avg_ms"] / 1000, 2), round(prev["avg_ms"] / 1000, 2)),
        "p50_ms": _cmp(cur["p50"], prev["p50"]),
        "p95_ms": _cmp(cur["p95"], prev["p95"]),
        "p50_s": _cmp(round(cur["p50"] / 1000, 2), round(prev["p50"] / 1000, 2)),
        "p95_s": _cmp(round(cur["p95"] / 1000, 2), round(prev["p95"] / 1000, 2)),
        "avg_sql_exec_ms": _cmp(cur["avg_sql_ms"], prev["avg_sql_ms"]),
        "total_cost": _cmp(cur["cost"], prev["cost"]),
        "avg_cost_per_query": _cmp(ac, ap),
        "total_tokens": _cmp(cur["tokens"], prev["tokens"]),
        "input_tokens": _cmp(cur["input_tokens"], prev["input_tokens"]),
        "output_tokens": _cmp(cur["output_tokens"], prev["output_tokens"]),
        "unique_users": _cmp(cur["uniq"], prev["uniq"]),
        "sql_retries": _cmp(cur["retries"], prev["retries"]),
        "feedback_positive": _cmp(fb_cur["positive"], fb_prev["positive"]),
        "feedback_negative": _cmp(fb_cur["negative"], fb_prev["negative"]),
        "feedback_positive_rate": _cmp(_positive_rate(fb_cur), _positive_rate(fb_prev)),  # delta in pp
    }


@track_time("DB: Agent Health - scorecard")
async def get_agent_scorecard(
    *, agent_id: str, period: str = "week", top_n: int = 10,
    bucket: str = "day",
    start: Optional[datetime] = None, end: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    # usage.per_day granularity: "hour" | "day" | "week" | "month" (date_trunc unit).
    bucket = bucket if bucket in ("hour", "day", "week", "month") else "day"
    since, until = _resolve_window(period, start, end)
    async with async_session() as session:
        cur = await _window_aggregates(session, agent_id, since, until)
        if cur["total"] == 0:
            # 404 signal — no rows ever for this agent. Caller decides.
            if not await _agent_seen(session, agent_id):
                return None
        conds = [_E.agent_id == agent_id, _E.event_ts >= since, _E.event_ts < until]
        per_day = (await session.execute(
            select(func.date_trunc(bucket, _E.event_ts).label("d"), func.count().label("c"))
            .where(and_(*conds)).group_by("d").order_by("d")
        )).all()
        by_model = (await session.execute(
            select(_E.provider, _E.model, func.count().label("c"), _cost_sum.label("cost"))
            .where(and_(*conds)).group_by(_E.provider, _E.model).order_by(func.count().desc())
        )).all()
        # NL2SQL-specific: which route answered, and which database was queried.
        by_route = (await session.execute(
            select(_E.route, func.count().label("c"), _sum_answered.label("answered"),
                   func.avg(_E.latency_ms).label("avg_ms"))
            .where(and_(*conds)).group_by(_E.route).order_by(func.count().desc())
        )).all()
        by_db = (await session.execute(
            select(_E.db_id, func.count().label("c"), _sum_answered.label("answered"),
                   func.avg(_E.latency_ms).label("avg_ms"),
                   func.avg(_E.sql_exec_ms).label("avg_sql_ms"))
            .where(and_(*conds, _E.db_id.isnot(None)))
            .group_by(_E.db_id).order_by(func.count().desc())
        )).all()
        slowest = (await session.execute(
            select(_E.chat_id, _E.query, _E.latency_ms, _E.total_tokens, _E.trace_id)
            .where(and_(*conds)).order_by(_E.latency_ms.desc()).limit(top_n)
        )).all()
        most_exp = (await session.execute(
            select(_E.chat_id, _E.query, _E.total_tokens, _E.cost_usd, _E.trace_id)
            .where(and_(*conds)).order_by(_E.cost_usd.desc().nullslast(), _E.total_tokens.desc())
            .limit(top_n)
        )).all()
        # Feedback counts (positive/negative) for this agent's window — joined from
        # nl2sql_logs by the shared chat_id.
        fb_counts = (await session.execute(
            select(ChatLogs.feedback, func.count().label("c")).where(
                ChatLogs.chat_id.in_(select(_E.chat_id).where(and_(*conds))),
                ChatLogs.feedback.isnot(None),
            ).group_by(ChatLogs.feedback)
        )).all()
        # Per-node breakdown (current window). Previous-period comparison → /trends.
        cur_nodes = await _node_agg(session, agent_id, since, until)

    by_node = _build_by_node(cur_nodes)
    _feedback = {"positive": 0, "negative": 0}
    for fr in fb_counts:
        if fr.feedback in _feedback:
            _feedback[fr.feedback] = int(fr.c or 0)
    _feedback["total"] = _feedback["positive"] + _feedback["negative"]
    return {
        "agent_id": agent_id, "name": None, "period": period,
        "since": _to_utc_z(since), "until": _to_utc_z(until),
        # NOTE: previous-period comparison (current vs prev) is served by /trends.
        "usage": {
            "total_queries": cur["total"], "unique_users": cur["uniq"],
            "widget_queries": cur["widget"],
            # `bucket` = granularity; each point carries the full ISO bucket-start
            # timestamp (`bucket`, e.g. hour) AND the date (`day`, back-compat).
            "bucket": bucket,
            "per_day": [{"bucket": _to_utc_z(d.d),
                         "day": _to_utc_z(d.d)[:10] if d.d else None,
                         "queries": int(d.c or 0)} for d in per_day],
        },
        "quality": {
            # Headline (is_answered-based, per the dashboard's metric definitions):
            "answered": cur["answered"],              # is_answered = true
            "unanswered": cur["unanswered"],          # is_answered = false
            "success_rate": cur["success_rate"],      # answered / total_queries
            "failed_api_requests": cur["errors"],     # status = error
            "no_answer": cur["no_answer"],
            "sql_retries": cur["retries"],            # SQL regenerated after an exec error
            "feedback": _feedback,                    # {positive, negative, total} from nl2sql_logs
        },
        # NL2SQL routing: how questions were answered and which databases served them.
        "routing": {
            "cross_db_queries": cur["cross_db"], "pandas_queries": cur["pandas"],
            "chart_queries": cur["charts"],
            "by_route": [{"route": b.route, "queries": int(b.c or 0),
                          "answered": int(b.answered or 0),
                          "success_rate": _safe_rate(int(b.answered or 0), int(b.c or 0)),
                          "avg_ms": int(b.avg_ms) if b.avg_ms is not None else 0}
                         for b in by_route],
            "by_database": [{"db_id": b.db_id, "queries": int(b.c or 0),
                             "answered": int(b.answered or 0),
                             "success_rate": _safe_rate(int(b.answered or 0), int(b.c or 0)),
                             "avg_ms": int(b.avg_ms) if b.avg_ms is not None else 0,
                             "avg_sql_exec_ms": int(b.avg_sql_ms) if b.avg_sql_ms is not None else 0}
                            for b in by_db],
        },
        "perf": {"avg_ms": cur["avg_ms"], "p50_ms": cur["p50"], "p95_ms": cur["p95"],
                 # Time inside the customer's database — the part we don't control.
                 "avg_sql_exec_ms": cur["avg_sql_ms"],
                 # Per-node latency (avg/p50/p95, current window).
                 "by_node": by_node,
                 "slowest": [{"chat_id": s.chat_id, "query": s.query, "latency_ms": int(s.latency_ms or 0),
                              "total_tokens": int(s.total_tokens or 0), "trace_id": s.trace_id} for s in slowest]},
        "cost": {"total_cost": cur["cost"],
                 "avg_cost_per_query": round(cur["cost"] / cur["total"], 6) if cur["total"] else 0.0,
                 "total_tokens": cur["tokens"], "input_tokens": cur["input_tokens"],
                 "output_tokens": cur["output_tokens"], "cost_complete": cur["cost_complete"],
                 "by_model": [{"provider": b.provider, "model": b.model, "queries": int(b.c or 0),
                               "cost": round(float(b.cost), 6) if b.cost is not None else None} for b in by_model],
                 # Per-node cost + tokens (current window; same objects as perf.by_node).
                 "by_node": by_node,
                 "most_expensive": [{"chat_id": e.chat_id, "query": e.query, "total_tokens": int(e.total_tokens or 0),
                                     "cost_usd": float(e.cost_usd) if e.cost_usd is not None else None,
                                     "trace_id": e.trace_id} for e in most_exp]},
    }


# ── READ §4: failures ────────────────────────────────────────────────────────
@track_time("DB: Agent Health - failures")
async def get_agent_failures(
    *, agent_id: str, period: str = "week", category: Optional[str] = None,
    failed_stage: Optional[str] = None, limit: int = 50, offset: int = 0,
    start: Optional[datetime] = None, end: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    since, until = _resolve_window(period, start, end)
    base = [_E.agent_id == agent_id, _E.event_ts >= since, _E.event_ts < until,
            _E.status.in_(FAILURE_STATUSES)]
    flt = list(base)
    if category:
        flt.append(_E.failure_category == category)
    if failed_stage:
        flt.append(_E.failed_stage == failed_stage)

    async with async_session() as session:
        total_failures = (await session.execute(
            select(func.count()).where(and_(*base))
        )).scalar() or 0
        if total_failures == 0 and not await _agent_seen(session, agent_id):
            return None  # 404 — unknown agent (vs. known agent with no failures)
        by_cat = (await session.execute(
            select(_E.failure_category, func.count().label("c"))
            .where(and_(*base)).group_by(_E.failure_category).order_by(func.count().desc())
        )).all()
        by_stage = (await session.execute(
            select(_E.failed_stage, func.count().label("c"))
            .where(and_(*base)).group_by(_E.failed_stage).order_by(func.count().desc())
        )).all()
        # NL2SQL-specific: which database the failures came from — one broken connection
        # or one badly-described schema shows up here, not in the category split.
        by_db = (await session.execute(
            select(_E.db_id, func.count().label("c"))
            .where(and_(*base, _E.db_id.isnot(None)))
            .group_by(_E.db_id).order_by(func.count().desc())
        )).all()
        norm = func.lower(func.btrim(_E.query))
        top = (await session.execute(
            select(
                norm.label("qn"),
                func.max(_E.failure_category).label("fc"),
                func.max(_E.failed_stage).label("fs"),
                func.count().label("occ"),
                func.max(_E.event_ts).label("last_seen"),
                func.min(_E.event_ts).label("first_seen"),
                func.max(_E.failure_detail).label("detail"),
                func.max(_E.sql_query).label("sql"),
            ).where(and_(*flt)).group_by(norm)
            .order_by(func.count().desc(), func.max(_E.event_ts).desc())
            .limit(limit).offset(offset)
        )).all()

    tf = int(total_failures)
    return {
        "agent_id": agent_id, "period": period,
        "since": _to_utc_z(since), "until": _to_utc_z(until),
        "total_failures": tf,
        "filters": {"category": category, "failed_stage": failed_stage},
        "by_category": [{"failure_category": c.failure_category, "count": int(c.c or 0),
                         "pct": _safe_rate(int(c.c or 0), tf)} for c in by_cat],
        "by_stage": [{"failed_stage": s.failed_stage, "count": int(s.c or 0)} for s in by_stage],
        "by_database": [{"db_id": d.db_id, "count": int(d.c or 0)} for d in by_db],
        "limit": limit, "offset": offset, "returned": len(top),
        "top_failed_queries": [{
            "query_norm": t.qn, "failure_category": t.fc, "failed_stage": t.fs,
            "occurrences": int(t.occ or 0), "last_seen": _to_utc_z(t.last_seen),
            "first_seen": _to_utc_z(t.first_seen), "sample_failure_detail": t.detail,
            "sample_sql": t.sql,
        } for t in top],
    }


# ── READ §5: trends ──────────────────────────────────────────────────────────
@track_time("DB: Agent Health - trends")
async def get_agent_trends(
    *, agent_id: str, weeks: int = 8, bucket: str = "week",
    metrics: Optional[List[str]] = None,
    start: Optional[datetime] = None, end: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    # Explicit [start, end) (Custom Range) overrides the trailing `weeks` window;
    # `bucket` still controls the date_trunc granularity within the range.
    if start is not None and end is not None:
        since, until = _to_naive_utc(start), _to_naive_utc(end)
    else:
        per = {"week": 7, "day": 1, "month": 30}.get(bucket, 7)
        until = datetime.utcnow()
        since = until - timedelta(days=per * weeks)
    wanted = metrics or ["success_rate", "avg_ms", "cost", "failures"]
    conds = [_E.agent_id == agent_id, _E.event_ts >= since, _E.event_ts < until]
    b = func.date_trunc(bucket, _E.event_ts).label("b")
    async with async_session() as session:
        rows = (await session.execute(
            select(
                b, func.count().label("total"),
                _sum_answered.label("answered"),
                _sum_failed.label("failed"),
                func.avg(_E.latency_ms).label("avg_ms"),
                _p95.label("p95"),
                _cost_sum.label("cost"),
            ).where(and_(*conds)).group_by("b").order_by("b")
        )).all()
        if not rows and not await _agent_seen(session, agent_id):
            return None  # 404 — unknown agent (vs. known agent with no data in range)
        # Current-vs-previous-period comparison for every headline metric (this is the
        # home for all "vs prev period" data; the scorecard stays current-state).
        comparison = await _period_comparison(session, agent_id, since, until)

    series = []
    for r in rows:
        total = int(r.total or 0)
        point = {"bucket": _to_utc_z(r.b), "trusted": True, "total_queries": total}
        if "success_rate" in wanted:
            # Success Rate = Answered / Total.
            point["success_rate"] = _safe_rate(int(r.answered or 0), total)
        if "avg_ms" in wanted:
            point["avg_ms"] = int(r.avg_ms) if r.avg_ms is not None else None
        if "p95_ms" in wanted:
            point["p95_ms"] = int(r.p95) if r.p95 is not None else None
        if "cost" in wanted:
            point["cost"] = round(float(r.cost or 0), 6)
        if "failures" in wanted:
            point["failures"] = int(r.failed or 0)
        series.append(point)

    regression = {"detected": False}
    if "success_rate" in wanted and len(series) >= 2:
        prev_p, last_p = series[-2], series[-1]
        d = (last_p.get("success_rate") or 0) - (prev_p.get("success_rate") or 0)
        # One-way: flag a >=5pp DROP between adjacent buckets only. Upward spikes
        # (improvements) are never a health concern, so they're intentionally not flagged.
        if d <= -5:
            regression = {"detected": True, "metric": "success_rate",
                          "from_bucket": prev_p["bucket"], "to_bucket": last_p["bucket"],
                          "delta": round(d, 1), "note": "step-change in success_rate between adjacent buckets"}
    return {"agent_id": agent_id, "bucket": bucket, "buckets": len(series),
            "since": _to_utc_z(since), "until": _to_utc_z(until),
            # Current-vs-previous-period comparison: {current, previous, delta,
            # pct_change} per metric (delta for rates in pp). previous_since inside.
            "comparison": comparison,
            "metrics": wanted, "series": series, "regression": regression}


# ── READ §6: per-query drill-down ────────────────────────────────────────────
_QUERY_SORTS = {
    "latency_ms": _E.latency_ms, "cost_usd": _E.cost_usd, "total_tokens": _E.total_tokens,
    "retry_count": _E.retry_count, "created_at": _E.event_ts,
}
_OUTCOME_OF = {**{s: "success" for s in SUCCESS_STATUSES},
               **{s: "failure" for s in FAILURE_STATUSES},
               **{s: "excluded" for s in EXCLUDED_STATUSES}}


def _row_to_query_dict(r: AgentHealthEvent, feedback: Optional[str] = None,
                       include_node_data: bool = True) -> Dict[str, Any]:
    d: Dict[str, Any] = {
        "chat_id": r.chat_id, "session_id": r.session_id, "user_id": r.user_id,
        "request_id": r.request_id,
        "timestamp": _to_utc_z(r.event_ts), "query": r.query, "refined_query": r.refined_query,
        "route": r.route, "nodes_used": r.nodes_used or [],
        # What NL2SQL actually did — the drill-down a SQL agent's operator needs.
        "db_id": r.db_id, "db_ids": r.db_ids or [], "cross_db": bool(r.cross_db),
        "sql_query": r.sql_query, "selected_tables": r.selected_tables or [],
        "rows_returned": r.rows_returned, "pandas_used": bool(r.pandas_used),
        "chart_generated": bool(r.chart_generated),
        "status": r.status, "outcome": _OUTCOME_OF.get(r.status or "", None),
        "is_answered": bool(r.is_answered),
        "failure_category": r.failure_category, "failed_stage": r.failed_stage,
        "failure_detail": r.failure_detail, "provider": r.provider, "model": r.model,
        # feedback: "positive" / "negative" / None — from nl2sql_logs, joined on chat_id.
        "from_widget": bool(r.from_widget), "key_type": r.key_type, "feedback": feedback,
        "metrics": {"latency_ms": r.latency_ms, "db_fetch_ms": r.db_fetch_ms,
                    "sql_exec_ms": r.sql_exec_ms,
                    "input_tokens": r.input_tokens, "output_tokens": r.output_tokens,
                    "total_tokens": r.total_tokens,
                    "cost_usd": float(r.cost_usd) if r.cost_usd is not None else None,
                    "cost_complete": bool(r.cost_complete),
                    # Per-NODE breakdown (model + tokens + latency + cost once priced).
                    "node_data": r.node_data or [],
                    "retry_count": r.retry_count},
        "trace_id": r.trace_id,
        "langsmith_run_id": r.langsmith_run_id,
    }
    if not include_node_data:
        # Strip the heavy node-level breakdown from list rows when not requested.
        d["metrics"].pop("node_data", None)
    return d


@track_time("DB: Agent Health - queries")
async def list_agent_queries(
    *, agent_id: str, period: str = "week", sort: str = "latency_ms", order: str = "desc",
    status: Optional[str] = None, outcome: Optional[str] = None,
    failure_category: Optional[str] = None, failed_stage: Optional[str] = None,
    route: Optional[str] = None, model: Optional[str] = None, db_id: Optional[str] = None,
    min_tokens: Optional[int] = None, min_cost_usd: Optional[float] = None,
    min_latency_ms: Optional[int] = None, chat_id: Optional[str] = None,
    feedback: Optional[str] = None, include_node_data: bool = True,
    start: Optional[datetime] = None, end: Optional[datetime] = None,
    limit: int = 20, offset: int = 0,
) -> Optional[Dict[str, Any]]:
    conds = [_E.agent_id == agent_id]
    if chat_id:
        # Exact lookup bypasses the time window but STAYS scoped to this agent
        # (agent isolation — never return another agent's row under this agent_id).
        conds.append(_E.chat_id == chat_id)
    else:
        since, until = _resolve_window(period, start, end)
        conds += [_E.event_ts >= since, _E.event_ts < until]
        if status:
            # Status is binary: "answered" / "unanswered" (aka "no_answer"). Filter on
            # is_answered so it works regardless of the stored status string; any other
            # value falls back to an exact match.
            s = status.strip().lower()
            if s == "answered":
                conds.append(_E.is_answered.is_(True))
            elif s in ("unanswered", "no_answer"):
                conds.append(_E.is_answered.is_(False))
            else:
                conds.append(_E.status == status)
        if outcome:
            buckets = {"success": SUCCESS_STATUSES, "failure": FAILURE_STATUSES,
                       "excluded": EXCLUDED_STATUSES}
            if outcome in buckets and buckets[outcome]:
                conds.append(_E.status.in_(buckets[outcome]))
        if failure_category:
            conds.append(_E.failure_category == failure_category)
        if failed_stage:
            conds.append(_E.failed_stage == failed_stage)
        if route:
            conds.append(_E.route == route)
        if model:
            conds.append(_E.model == model)
        if db_id:
            conds.append(_E.db_id == db_id)
        if min_tokens is not None:
            conds.append(_E.total_tokens >= min_tokens)
        if min_cost_usd is not None:
            # NULL cost_usd (unpriced rows) is excluded by SQL NULL-comparison semantics
            # — this filter matches priced rows only, intentionally.
            conds.append(_E.cost_usd >= min_cost_usd)
        if min_latency_ms is not None:
            conds.append(_E.latency_ms >= min_latency_ms)
        if feedback:
            # Feedback lives on nl2sql_logs (positive/negative), keyed by chat_id.
            fb = feedback.strip().lower()
            _rated = select(ChatLogs.chat_id).where(ChatLogs.feedback.isnot(None))
            if fb == "positive":
                conds.append(_E.chat_id.in_(select(ChatLogs.chat_id).where(ChatLogs.feedback == "positive")))
            elif fb == "negative":
                conds.append(_E.chat_id.in_(select(ChatLogs.chat_id).where(ChatLogs.feedback == "negative")))
            elif fb in ("none", "unrated"):
                conds.append(_E.chat_id.notin_(_rated))
            elif fb in ("any", "rated"):
                conds.append(_E.chat_id.in_(_rated))

    col = _QUERY_SORTS.get(sort, _E.latency_ms)
    order_by = (col.desc().nullslast() if order == "desc" else col.asc().nullsfirst())

    async with async_session() as session:
        total = (await session.execute(select(func.count()).where(and_(*conds)))).scalar() or 0
        if total == 0 and not await _agent_seen(session, agent_id):
            return None  # 404 — unknown agent
        rows = (await session.execute(
            select(_E).where(and_(*conds)).order_by(order_by).limit(limit).offset(offset)
        )).scalars().all()

        # Feedback (positive/negative) is stored on nl2sql_logs, keyed by the SAME
        # chat_id — look it up for this page and attach per row.
        fb_map: Dict[str, Any] = {}
        if rows:
            fb_rows = (await session.execute(
                select(ChatLogs.chat_id, ChatLogs.feedback).where(
                    ChatLogs.chat_id.in_([r.chat_id for r in rows]),
                    ChatLogs.feedback.isnot(None),
                )
            )).all()
            fb_map = {fr.chat_id: fr.feedback for fr in fb_rows}

    return {
        "agent_id": agent_id, "period": (None if chat_id else period),
        "sort": sort, "order": order, "total_matching": int(total),
        "limit": limit, "offset": offset, "returned": len(rows),
        "queries": [_row_to_query_dict(r, feedback=fb_map.get(r.chat_id),
                                       include_node_data=include_node_data) for r in rows],
    }
