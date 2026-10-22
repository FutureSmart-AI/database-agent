"""Database access for Batch Query Reports.

NL2SQL is the system of record for its own reports. These helpers own the report/run tables
and derive every progress count from stored results — nothing reports counts to us, so they
can never drift from the rows that actually exist.
"""
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlmodel import and_, select

from agent.services.sqlmodel_session import async_session
from logger import logger
from otel_tracing import track_time

from batch_query_reports import reports_env
from batch_query_reports.pydantic_model_db import (
    Report,
    ReportRun,
    ReportRunGroup,
    ReportRunQuery,
    ReportRunResult,
    ReportSettings,
)
from batch_query_reports.schedule_utils import compute_next_run_at


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def _duration_ms(started: Optional[datetime], ended: Optional[datetime]) -> Optional[int]:
    """Wall-clock time of a run = ended_at - started_at, in ms. None until both are set."""
    if started and ended:
        return int((ended - started).total_seconds() * 1000)
    return None


def _to_naive_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Coerce a datetime to naive UTC for storage.

    The run timestamp columns are TIMESTAMP WITHOUT TIME ZONE, but an external worker sends
    ISO-8601 datetimes carrying a timezone ('Z' or an offset). asyncpg refuses to bind a
    tz-aware value to a naive column, so convert to UTC and drop the tzinfo. Naive inputs
    pass through unchanged.
    """
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


# ---------------------------------------------------------------------------
# Settings (per-agent, runtime-configurable)
# ---------------------------------------------------------------------------

async def _read_max_queries(session, agent_id: str) -> int:
    """Effective per-report query cap for an agent: its stored value, else the env default."""
    row = (await session.execute(
        select(ReportSettings).where(ReportSettings.agent_id == agent_id)
    )).scalar_one_or_none()
    if row and row.max_queries_per_report is not None:
        return row.max_queries_per_report
    return reports_env.REPORTS_MAX_QUERIES_PER_REPORT


async def get_effective_query_limit(agent_id: str) -> int:
    """The limit enforcement should use for this agent."""
    async with async_session() as session:
        return await _read_max_queries(session, agent_id)


@track_time("DB: Get Report Settings")
async def get_report_settings(agent_id: str) -> Dict[str, Any]:
    """An agent's effective query limit plus the system default.

    The default is returned so the frontend never hardcodes it. `updated_by`/`updated_at` are
    recorded for audit but not exposed.
    """
    return {
        "max_queries_per_report": await get_effective_query_limit(agent_id),
        "default_max_queries_per_report": reports_env.REPORTS_MAX_QUERIES_PER_REPORT,
    }


@track_time("DB: Update Report Settings")
async def update_max_queries_per_report(
    agent_id: str, value: int, updated_by: Optional[str]
) -> Dict[str, Any]:
    """Set an agent's per-report query cap (upserts its row). Returns the new settings."""
    async with async_session() as session:
        row = (await session.execute(
            select(ReportSettings).where(ReportSettings.agent_id == agent_id)
        )).scalar_one_or_none()
        if not row:
            row = ReportSettings(agent_id=agent_id)
            session.add(row)
        row.max_queries_per_report = value
        row.updated_at = datetime.utcnow()
        row.updated_by = updated_by
        await session.commit()
    logger.info(
        f"Report settings updated for agent {agent_id}: "
        f"max_queries_per_report={value} by {updated_by}"
    )
    return await get_report_settings(agent_id)


async def agent_exists(agent_id: str) -> bool:
    """Whether the agent exists at all.

    Reports are agent-scoped, and RBAC alone would happily create a report for a typo'd id —
    so every entry point checks this first and returns 404 instead. Both id columns are
    accepted because older agents are keyed by `chatbot_id`.
    """
    from models.sql_models import ChatbotDetails
    from sqlmodel import or_

    async with async_session() as session:
        row = (await session.execute(
            select(ChatbotDetails.agent_id).where(or_(
                ChatbotDetails.agent_id == agent_id,
                ChatbotDetails.chatbot_id == agent_id,
            ))
        )).first()
    return row is not None


class QueryLimitExceeded(Exception):
    """A report has more queries than the effective cap allows.

    Raised at run creation — the one choke point every run passes through — so a report that
    already exceeded the limit (or predates a lowered one) cannot be run.
    """

    def __init__(self, total_queries: int, limit: int):
        self.total_queries = total_queries
        self.limit = limit
        super().__init__(f"Report has {total_queries} queries, exceeding the limit of {limit}.")


# ---------------------------------------------------------------------------
# Report definition (template)
# ---------------------------------------------------------------------------

@track_time("DB: Create Report")
async def create_report(
    agent_id: str,
    user_id: Optional[str],
    name: str,
    query_groups: List[Dict[str, Any]],
    report_instructions: Optional[str] = None,
    analysis_prompt: Optional[str] = None,
    schedule: Optional[Dict[str, Any]] = None,
) -> str:
    """Insert a report definition and return its report_id."""
    report_id = _new_id("rep")
    async with async_session() as session:
        session.add(Report(
            report_id=report_id,
            agent_id=agent_id,
            user_id=user_id or "",
            name=name,
            report_instructions=report_instructions,
            query_groups=query_groups,
            analysis_prompt=analysis_prompt,
            schedule=schedule,
            next_run_at=_to_naive_utc(compute_next_run_at(schedule)),
            created_at=datetime.utcnow(),
            # updated_at stays NULL until the first real update.
            deleted=False,
        ))
        await session.commit()
    logger.info(f"Created report {report_id} for agent {agent_id}")
    return report_id


async def _get_report_row(session, report_id: str) -> Optional[Report]:
    result = await session.execute(
        select(Report).where(
            and_(Report.report_id == report_id, Report.deleted == False)  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


def _report_to_dict(r: Report) -> Dict[str, Any]:
    return {
        "report_id": r.report_id,
        "agent_id": r.agent_id,
        "user_id": r.user_id,
        "name": r.name,
        "report_instructions": r.report_instructions,
        "query_groups": r.query_groups,
        "analysis_prompt": r.analysis_prompt,
        "schedule": r.schedule,
        "next_run_at": _iso(r.next_run_at),
        "created_at": _iso(r.created_at),
        "updated_at": _iso(r.updated_at),
    }


@track_time("DB: Get Report")
async def get_report(report_id: str) -> Optional[Dict[str, Any]]:
    async with async_session() as session:
        r = await _get_report_row(session, report_id)
        return _report_to_dict(r) if r else None


@track_time("DB: List Reports")
async def list_reports(agent_id: str) -> List[Dict[str, Any]]:
    async with async_session() as session:
        result = await session.execute(
            select(Report)
            .where(and_(Report.agent_id == agent_id, Report.deleted == False))  # noqa: E712
            .order_by(Report.created_at.desc())
        )
        return [_report_to_dict(r) for r in result.scalars().all()]


@track_time("DB: Update Report")
async def update_report(report_id: str, fields: Dict[str, Any]) -> bool:
    """Update the mutable report fields present in `fields`.

    The router has already decided what to write, so a None here is an intentional clear
    (e.g. removing a schedule) and must NOT be filtered out — otherwise a field could never
    be unset.
    """
    async with async_session() as session:
        r = await _get_report_row(session, report_id)
        if not r:
            return False
        for key, value in fields.items():
            setattr(r, key, value)
        # A changed schedule re-bases the due pointer from now; a cleared one nulls it so the
        # scheduler stops picking the report up.
        if "schedule" in fields:
            r.next_run_at = _to_naive_utc(compute_next_run_at(fields["schedule"]))
        r.updated_at = datetime.utcnow()
        await session.commit()
    logger.info(f"Updated report {report_id}: fields={list(fields.keys())}")
    return True


@track_time("DB: Delete Report")
async def soft_delete_report(report_id: str, deleted_by: Optional[str] = None) -> bool:
    async with async_session() as session:
        r = await _get_report_row(session, report_id)
        if not r:
            return False
        r.deleted = True
        r.deleted_by = deleted_by
        # Its own timestamp, so delete-time is never conflated with the last content edit.
        r.deleted_at = datetime.utcnow()
        # A deleted report must stop firing even though the row survives.
        r.next_run_at = None
        await session.commit()
    logger.info(f"Soft-deleted report {report_id} by {deleted_by}")
    return True


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------

@track_time("DB: Claim Due Reports")
async def claim_due_reports(now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Atomically claim every report whose scheduled run is due, advancing its next_run_at.

    Due rows (schedule set, next_run_at <= now, not deleted) are selected FOR UPDATE SKIP
    LOCKED and advanced to their following occurrence in the SAME transaction. That makes the
    tick safe on every replica: each due report is claimed by exactly one instance (the others
    skip the locked row) and therefore fires exactly once.

    A report whose schedule no longer yields a next time is advanced to NULL — it has fired for
    the last time and won't be picked up again until rescheduled.
    """
    now = now or datetime.utcnow()
    claimed: List[Dict[str, Any]] = []
    async with async_session() as session:
        rows = (await session.execute(
            select(Report)
            .where(and_(
                Report.deleted == False,  # noqa: E712
                Report.schedule.isnot(None),
                Report.next_run_at.isnot(None),
                Report.next_run_at <= now,
            ))
            .with_for_update(skip_locked=True)
        )).scalars().all()
        for r in rows:
            # Advance FIRST, under the lock, so the row stops being "due" the moment we commit.
            r.next_run_at = _to_naive_utc(compute_next_run_at(r.schedule, now))
            claimed.append({
                "report_id": r.report_id,
                "agent_id": r.agent_id,
                "schedule": r.schedule,
                "next_run_at": _iso(r.next_run_at),
            })
        await session.commit()
    return claimed


# ---------------------------------------------------------------------------
# Run creation + pre-materialization
# ---------------------------------------------------------------------------

@track_time("DB: Create Run")
async def create_run(
    report_id: str, trigger: str = "manual", user_id: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Create a run from a report definition, pre-materializing its groups and queries with
    stable IDs. Returns {run_id, total_queries}, or None if the report is gone.

    Pre-materialization is what makes result writes idempotent: both the executor and the
    stored results reference IDs that exist before any query runs.
    """
    if not user_id:
        user_id = "system"

    async with async_session() as session:
        report = await _get_report_row(session, report_id)
        if not report:
            return None

        # The cap is enforced here, at the single point every run (manual or scheduled) passes
        # through, using the agent's runtime-configurable limit.
        limit = await _read_max_queries(session, report.agent_id)
        query_count = sum(len(g.get("queries") or []) for g in (report.query_groups or []))
        if query_count > limit:
            raise QueryLimitExceeded(query_count, limit)

        run_id = _new_id("run")
        session.add(ReportRun(
            run_id=run_id,
            report_id=report.report_id,
            agent_id=report.agent_id,
            user_id=user_id,
            status="pending",
            trigger=trigger,
            created_at=datetime.utcnow(),
        ))

        total_queries = 0
        for g_index, group in enumerate(report.query_groups or []):
            group_id = _new_id("g")
            session.add(ReportRunGroup(
                group_id=group_id,
                run_id=run_id,
                type=group.get("type", "independent"),
                position=g_index,
            ))
            for q_index, text in enumerate(group.get("queries", [])):
                session.add(ReportRunQuery(
                    query_id=_new_id("q"),
                    run_id=run_id,
                    group_id=group_id,
                    position=q_index,
                    text=text,
                ))
                total_queries += 1

        await session.commit()

    logger.info(
        f"Created run {run_id} for report {report_id} "
        f"({total_queries} queries, trigger={trigger})"
    )
    return {"run_id": run_id, "total_queries": total_queries}


async def _get_run_row(session, run_id: str) -> Optional[ReportRun]:
    result = await session.execute(select(ReportRun).where(ReportRun.run_id == run_id))
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Progress derivation
# ---------------------------------------------------------------------------

async def _derive_progress(session, run_id: str) -> Dict[str, int]:
    total = (await session.execute(
        select(func.count()).select_from(ReportRunQuery).where(ReportRunQuery.run_id == run_id)
    )).scalar_one()

    completed = (await session.execute(
        select(func.count()).select_from(ReportRunResult).where(
            and_(ReportRunResult.run_id == run_id, ReportRunResult.error.is_(None))
        )
    )).scalar_one()

    failed = (await session.execute(
        select(func.count()).select_from(ReportRunResult).where(
            and_(ReportRunResult.run_id == run_id, ReportRunResult.error.is_not(None))
        )
    )).scalar_one()

    done = completed + failed
    return {
        "total_queries": total,
        "completed_queries": completed,
        "failed_queries": failed,
        "percent_complete": int(round(done / total * 100)) if total else 0,
    }


@track_time("DB: Get Run Status")
async def get_run_status(run_id: str) -> Optional[Dict[str, Any]]:
    async with async_session() as session:
        run = await _get_run_row(session, run_id)
        if not run:
            return None
        progress = await _derive_progress(session, run_id)
        return {
            "run_id": run.run_id,
            "report_id": run.report_id,
            "agent_id": run.agent_id,
            "status": run.status,
            "progress": progress,
            "started_at": _iso(run.started_at),
            "ended_at": _iso(run.ended_at),
        }


@track_time("DB: List Runs")
async def list_runs(report_id: str) -> List[Dict[str, Any]]:
    """List a report's runs with progress, in three aggregate reads rather than 3-per-run."""
    async with async_session() as session:
        runs = (await session.execute(
            select(ReportRun)
            .where(ReportRun.report_id == report_id)
            .order_by(ReportRun.created_at.desc())
        )).scalars().all()
        if not runs:
            return []

        run_ids = [r.run_id for r in runs]

        totals = dict((await session.execute(
            select(ReportRunQuery.run_id, func.count())
            .where(ReportRunQuery.run_id.in_(run_ids))
            .group_by(ReportRunQuery.run_id)
        )).all())

        completed = dict((await session.execute(
            select(ReportRunResult.run_id, func.count())
            .where(and_(
                ReportRunResult.run_id.in_(run_ids),
                ReportRunResult.error.is_(None),
            ))
            .group_by(ReportRunResult.run_id)
        )).all())

        failed = dict((await session.execute(
            select(ReportRunResult.run_id, func.count())
            .where(and_(
                ReportRunResult.run_id.in_(run_ids),
                ReportRunResult.error.is_not(None),
            ))
            .group_by(ReportRunResult.run_id)
        )).all())

    out: List[Dict[str, Any]] = []
    for run in runs:
        total = totals.get(run.run_id, 0)
        done = completed.get(run.run_id, 0)
        bad = failed.get(run.run_id, 0)
        finished = done + bad
        out.append({
            "run_id": run.run_id,
            "report_id": run.report_id,
            "status": run.status,
            "trigger": run.trigger,
            "progress": {
                "total_queries": total,
                "completed_queries": done,
                "failed_queries": bad,
                "percent_complete": int(round(finished / total * 100)) if total else 0,
            },
            "started_at": _iso(run.started_at),
            "ended_at": _iso(run.ended_at),
            "total_time_ms": _duration_ms(run.started_at, run.ended_at),
            "created_at": _iso(run.created_at),
        })
    return out


# ---------------------------------------------------------------------------
# Run definition (executor fetch) + full run (user retrieve)
# ---------------------------------------------------------------------------

@track_time("DB: Get Run Definition")
async def get_run_definition(run_id: str) -> Optional[Dict[str, Any]]:
    """The pre-materialized definition with stable IDs, plus its report context.

    Read by both the in-process runner and (over HTTP) an external worker, so both drive a run
    from exactly the same payload.
    """
    async with async_session() as session:
        run = await _get_run_row(session, run_id)
        if not run:
            return None

        # Read the report even if it was soft-deleted meanwhile, so an in-flight run can still
        # finish with its instructions and analysis prompt intact.
        report = (await session.execute(
            select(Report).where(Report.report_id == run.report_id)
        )).scalar_one_or_none()

        groups = (await session.execute(
            select(ReportRunGroup)
            .where(ReportRunGroup.run_id == run_id)
            .order_by(ReportRunGroup.position)
        )).scalars().all()

        queries = (await session.execute(
            select(ReportRunQuery)
            .where(ReportRunQuery.run_id == run_id)
            .order_by(ReportRunQuery.position)
        )).scalars().all()

    queries_by_group: Dict[str, list] = {}
    for q in queries:
        queries_by_group.setdefault(q.group_id, []).append(
            {"query_id": q.query_id, "text": q.text}
        )

    return {
        "run_id": run.run_id,
        "report_id": run.report_id,
        "agent_id": run.agent_id,
        "user_id": run.user_id,
        "report_instructions": report.report_instructions if report else None,
        "analysis_prompt": report.analysis_prompt if report else None,
        "query_groups": [
            {
                "group_id": g.group_id,
                "type": g.type,
                "queries": queries_by_group.get(g.group_id, []),
            }
            for g in groups
        ],
    }


def _result_to_dict(r: ReportRunResult) -> Dict[str, Any]:
    return {
        "query_id": r.query_id,
        "group_id": r.group_id,
        "session_id": r.session_id,
        "chat_id": r.chat_id,
        "answer": r.answer,
        "execution_details": r.execution_details,
        "response_time_ms": r.response_time_ms,
        "token_usage": r.token_usage,
        "is_answered": r.is_answered,
        "error": r.error,
    }


@track_time("DB: Get Full Run")
async def get_run_full(run_id: str) -> Optional[Dict[str, Any]]:
    """The full assembled run — groups, per-query results, summary and analysis."""
    async with async_session() as session:
        run = await _get_run_row(session, run_id)
        if not run:
            return None

        report = (await session.execute(
            select(Report).where(Report.report_id == run.report_id)
        )).scalar_one_or_none()

        groups = (await session.execute(
            select(ReportRunGroup)
            .where(ReportRunGroup.run_id == run_id)
            .order_by(ReportRunGroup.position)
        )).scalars().all()

        queries = (await session.execute(
            select(ReportRunQuery)
            .where(ReportRunQuery.run_id == run_id)
            .order_by(ReportRunQuery.position)
        )).scalars().all()

        results = (await session.execute(
            select(ReportRunResult).where(ReportRunResult.run_id == run_id)
        )).scalars().all()

        progress = await _derive_progress(session, run_id)

    results_by_query = {r.query_id: r for r in results}
    queries_by_group: Dict[str, list] = {}
    for q in queries:
        queries_by_group.setdefault(q.group_id, []).append(q)

    times = [r.response_time_ms for r in results if r.response_time_ms is not None]
    tokens = [r.token_usage for r in results if r.token_usage is not None]

    group_blocks = []
    for g in groups:
        result_items = []
        conversation_flow = []
        for q in queries_by_group.get(g.group_id, []):
            r = results_by_query.get(q.query_id)
            item: Dict[str, Any] = {"question": q.text}
            if r:
                item.update(_result_to_dict(r))
            else:
                # A query with no result row yet (still running, or the run died before
                # reaching it) still appears, so the report always lists every question.
                item.update({
                    "query_id": q.query_id,
                    "group_id": q.group_id,
                    "session_id": None,
                    "chat_id": None,
                    "answer": None,
                    "execution_details": None,
                    "response_time_ms": None,
                    "token_usage": None,
                    "is_answered": None,
                    "error": None,
                })
            result_items.append(item)
            if g.type == "sequential":
                conversation_flow.append({
                    "question": q.text,
                    "answer": (r.answer if r else None),
                })

        block: Dict[str, Any] = {"group_id": g.group_id, "type": g.type, "results": result_items}
        if g.type == "sequential":
            block["conversation_flow"] = conversation_flow
        group_blocks.append(block)

    return {
        "run_id": run.run_id,
        "report_id": run.report_id,
        "name": report.name if report else None,
        "agent_id": run.agent_id,
        "status": run.status,
        "trigger": run.trigger,
        "executed_at": _iso(run.started_at or run.created_at),
        "started_at": _iso(run.started_at),
        "ended_at": _iso(run.ended_at),
        "failure_reason": run.failure_reason,
        "summary": {
            "total_queries": progress["total_queries"],
            "completed_queries": progress["completed_queries"],
            "failed_queries": progress["failed_queries"],
            "total_time_ms": _duration_ms(run.started_at, run.ended_at),
            "avg_response_time_ms": int(round(sum(times) / len(times))) if times else 0,
            "total_tokens": sum(tokens) if tokens else 0,
        },
        "overall_summary": run.overall_summary,
        "query_groups": group_blocks,
    }


# ---------------------------------------------------------------------------
# Executor writes: status, results, analysis (all idempotent)
# ---------------------------------------------------------------------------

# Once a run is in a terminal state a later transition cannot overwrite it.
TERMINAL_RUN_STATES = {"completed", "failed", "cancelled"}


@track_time("DB: Update Run Status")
async def update_run_status(
    run_id: str,
    status: str,
    started_at: Optional[datetime] = None,
    ended_at: Optional[datetime] = None,
    failure_reason: Optional[str] = None,
    updated_by: Optional[str] = None,
) -> Optional[str]:
    """Idempotent lifecycle transition. Returns the resulting status, or None if run missing.

    Re-sending the current state, or any transition once terminal, is a no-op — retries from
    an external worker must not resurrect a closed-out run.

    `updated_by` records the user behind a UI-driven transition (e.g. a manual cancel);
    executor-driven transitions leave it None so the audit trail stays honest.
    """
    # External timestamps arrive tz-aware; the columns are naive UTC.
    started_at = _to_naive_utc(started_at)
    ended_at = _to_naive_utc(ended_at)

    async with async_session() as session:
        run = await _get_run_row(session, run_id)
        if not run:
            return None

        if run.status == status or run.status in TERMINAL_RUN_STATES:
            logger.info(f"Run {run_id} status transition {run.status}→{status} is a no-op")
            return run.status

        run.status = status
        if status == "running" and run.started_at is None:
            run.started_at = started_at or datetime.utcnow()
        if status in TERMINAL_RUN_STATES:
            run.ended_at = ended_at or datetime.utcnow()
        if status == "failed":
            run.failure_reason = failure_reason
        run.updated_at = datetime.utcnow()
        if updated_by is not None:
            run.updated_by = updated_by
        await session.commit()
    logger.info(f"Run {run_id} → {status}")
    return status


_RESULT_FIELDS = (
    "group_id", "session_id", "chat_id", "answer", "execution_details",
    "response_time_ms", "token_usage", "is_answered", "error",
)


async def _backfill_token_usage(session, results: List[Dict[str, Any]]) -> None:
    """Fill in `token_usage` from `nl2sql_logs` for any result that arrived without it.

    Token counts are not in the chat response — they are written to `nl2sql_logs` when the turn
    is persisted — so an out-of-process producer (the Celery worker, which has no access to this
    database) cannot supply them. Resolving them here means every producer gets accurate
    `total_tokens` in the run summary, rather than only the in-process one.

    One query for the whole batch. Best-effort: a report must not fail over a missing metric.
    """
    pending = {
        item["chat_id"]: item
        for item in results
        if item.get("chat_id") and item.get("token_usage") in (None, "")
    }
    if not pending:
        return
    try:
        from models.sql_models import ChatLogs

        rows = (await session.execute(
            select(ChatLogs.chat_id, ChatLogs.tokens_consumed)
            .where(ChatLogs.chat_id.in_(list(pending)))
        )).all()
        for chat_id, tokens in rows:
            if tokens in (None, ""):
                continue
            try:
                pending[chat_id]["token_usage"] = int(float(tokens))
            except (TypeError, ValueError):
                continue
    except Exception as e:
        logger.debug(f"[reports] token usage backfill skipped: {e}")


@track_time("DB: Upsert Run Results")
async def upsert_results(run_id: str, results: List[Dict[str, Any]]) -> int:
    """Upsert results by (run_id, query_id), so a retry can never duplicate a row.

    Items whose `query_id` does not belong to this run are dropped with a warning instead of
    written — a stray result has nowhere to be displayed and would inflate derived progress.
    """
    if not results:
        return 0

    async with async_session() as session:
        await _backfill_token_usage(session, results)
        # Resolve the legal query_ids once, so the check below is O(1) per item.
        valid_query_ids = {
            row[0]
            for row in (await session.execute(
                select(ReportRunQuery.query_id).where(ReportRunQuery.run_id == run_id)
            )).all()
        }
        if not valid_query_ids:
            logger.warning(
                f"Upsert called for run {run_id} which has no query rows; ignoring "
                f"{len(results)} submitted item(s)"
            )
            return 0

        count = 0
        skipped = 0
        for item in results:
            query_id = item.get("query_id")
            if not query_id or query_id not in valid_query_ids:
                skipped += 1
                logger.warning(
                    f"Dropping result for run {run_id}: query_id {query_id!r} "
                    f"does not belong to this run"
                )
                continue

            existing = (await session.execute(
                select(ReportRunResult).where(and_(
                    ReportRunResult.run_id == run_id,
                    ReportRunResult.query_id == query_id,
                ))
            )).scalar_one_or_none()

            if existing:
                for key in _RESULT_FIELDS:
                    if key in item:
                        setattr(existing, key, item[key])
                existing.updated_at = datetime.utcnow()
            else:
                session.add(ReportRunResult(
                    run_id=run_id,
                    query_id=query_id,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                    **{key: item.get(key) for key in _RESULT_FIELDS},
                ))
            count += 1
        await session.commit()

    if skipped:
        logger.info(f"Upserted {count} results for run {run_id} (skipped {skipped} invalid)")
    else:
        logger.info(f"Upserted {count} results for run {run_id}")
    return count


@track_time("DB: Set Run Analysis")
async def set_run_analysis(run_id: str, overall_summary: str) -> bool:
    async with async_session() as session:
        run = await _get_run_row(session, run_id)
        if not run:
            return False
        run.overall_summary = overall_summary
        run.updated_at = datetime.utcnow()
        await session.commit()
    logger.info(f"Stored analysis summary for run {run_id}")
    return True


@track_time("DB: Cancel Run")
async def cancel_run(run_id: str, cancelled_by: Optional[str] = None) -> Optional[str]:
    """Soft cancel: mark the run cancelled unless it is already terminal.

    Soft, because interrupting a query already in flight is out of scope — the executor
    notices the cancellation between queries and stops there (see runner.py).
    """
    return await update_run_status(run_id, "cancelled", updated_by=cancelled_by)


async def is_run_cancelled(run_id: str) -> bool:
    """Whether a run has been cancelled (or otherwise closed out) since it started.

    The in-process runner checks this between queries so a cancel takes effect promptly
    instead of after the whole batch has run.
    """
    async with async_session() as session:
        run = await _get_run_row(session, run_id)
        return bool(run and run.status in TERMINAL_RUN_STATES)
