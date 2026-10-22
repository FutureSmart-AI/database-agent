"""Execute a report run in this process.

Execution semantics:
- `independent` group → its queries run **concurrently**, each in its own session.
- `sequential`  group → its queries run **in order**, sharing one session_id so later
  questions see the earlier answers.
- Different groups run concurrently with each other.

Two things differ from the equivalent worker-side runner (`fs-agent-workers`
`celery_utils/reports/runner.py`), both because this runs inside the API process:

1. **Fan-out is capped.** A shared semaphore bounds how many agent pipelines — and therefore
   how many source-database connections — a run may hold open at once, so a large report
   cannot starve interactive chat.
2. **Results are written directly**, not POSTed. There is no network in between, so there is
   no partially-delivered batch to retry.

Progress counts are always derived from the stored rows, so flushing after each group is what
makes a run's progress move while it is still executing.
"""
import asyncio
from typing import Any, Dict, List, Optional

from logger import logger

from batch_query_reports import chat_client, db_utils, reports_env


def _result_row(
    *,
    query_id: str,
    group_id: str,
    envelope: Dict[str, Any],
    error: Optional[str],
    session_id: Optional[str],
) -> Dict[str, Any]:
    """One row in the shape `db_utils.upsert_results` stores."""
    return {
        "query_id": query_id,
        "group_id": group_id,
        "session_id": session_id or envelope.get("session_id"),
        "chat_id": envelope.get("chat_id"),
        "answer": envelope.get("answer") or None,
        "execution_details": envelope.get("execution_details"),
        "response_time_ms": envelope.get("response_time_ms"),
        "token_usage": envelope.get("token_usage"),
        "is_answered": envelope.get("is_answered"),
        "error": error,
    }


def _skipped_row(*, query_id: str, group_id: str, reason: str) -> Dict[str, Any]:
    """A query that never ran. Recorded as failed so it is visible instead of just absent."""
    return {
        "query_id": query_id,
        "group_id": group_id,
        "session_id": None,
        "chat_id": None,
        "answer": None,
        "execution_details": None,
        "response_time_ms": 0,
        "token_usage": None,
        "is_answered": None,
        "error": reason,
    }


_CANCELLED = "skipped: run was cancelled"


async def _ask(
    *,
    semaphore: asyncio.Semaphore,
    run_id: str,
    agent_id: str,
    question: str,
    session_id: Optional[str],
    user_id: Optional[str],
    report_instructions: Optional[str],
):
    """Ask one question, holding a concurrency slot for the duration.

    The cancellation check happens after acquiring the slot, not before waiting for it: a query
    can sit in the semaphore queue for a long time on a large report, and starting it because it
    was cleared to run minutes ago would ignore a cancel issued in between.
    """
    async with semaphore:
        if await db_utils.is_run_cancelled(run_id):
            return {"response_time_ms": 0}, _CANCELLED
        return await chat_client.ask_agent(
            agent_id=agent_id,
            question=question,
            session_id=session_id,
            user_id=user_id,
            report_instructions=report_instructions,
        )


async def _run_independent_group(
    *,
    semaphore: asyncio.Semaphore,
    run_id: str,
    agent_id: str,
    user_id: Optional[str],
    group: Dict[str, Any],
    report_instructions: Optional[str],
) -> List[Dict[str, Any]]:
    """Run every query in the group concurrently, each in its own session.

    Rows come back in input order so the transcript the analysis step reads stays readable.
    """
    queries = group.get("queries") or []
    group_id = group.get("group_id")

    tasks = [
        _ask(
            semaphore=semaphore,
            run_id=run_id,
            agent_id=agent_id,
            question=q.get("text", ""),
            session_id=None,
            user_id=user_id,
            report_instructions=report_instructions,
        )
        for q in queries
    ]
    outcomes = await asyncio.gather(*tasks, return_exceptions=True)

    rows: List[Dict[str, Any]] = []
    for q, outcome in zip(queries, outcomes):
        if isinstance(outcome, BaseException):
            envelope, error = {"response_time_ms": 0}, f"runner exception: {outcome}"
        else:
            envelope, error = outcome
        row = _result_row(
            query_id=q.get("query_id"),
            group_id=group_id,
            envelope=envelope,
            error=error,
            session_id=None,
        )
        row["_question"] = q.get("text", "")  # local only; stripped before storage
        rows.append(row)
    return rows


async def _run_sequential_group(
    *,
    semaphore: asyncio.Semaphore,
    run_id: str,
    agent_id: str,
    user_id: Optional[str],
    group: Dict[str, Any],
    report_instructions: Optional[str],
) -> List[Dict[str, Any]]:
    """Run the group's queries in order, reusing one session so each step sees prior turns.

    A failed step aborts the rest of the group: a follow-up question whose context never
    arrived would produce a confidently wrong answer, which is worse than a recorded skip.
    """
    queries = group.get("queries") or []
    group_id = group.get("group_id")
    rows: List[Dict[str, Any]] = []
    session_id: Optional[str] = None
    aborted_reason: Optional[str] = None

    for q in queries:
        if aborted_reason:
            row = _skipped_row(query_id=q.get("query_id"), group_id=group_id, reason=aborted_reason)
            row["_question"] = q.get("text", "")
            rows.append(row)
            continue

        envelope, error = await _ask(
            semaphore=semaphore,
            run_id=run_id,
            agent_id=agent_id,
            question=q.get("text", ""),
            session_id=session_id,
            user_id=user_id,
            report_instructions=report_instructions,
        )
        # Pin the session for the remaining steps as soon as we know it.
        if not session_id and envelope.get("session_id"):
            session_id = envelope["session_id"]

        row = _result_row(
            query_id=q.get("query_id"),
            group_id=group_id,
            envelope=envelope,
            error=error,
            session_id=session_id,
        )
        row["_question"] = q.get("text", "")
        rows.append(row)

        if error == _CANCELLED:
            # The run was cancelled, not broken — say so, rather than blaming the prior step.
            aborted_reason = _CANCELLED
        elif error:
            aborted_reason = "skipped: previous step in sequential group failed"

    return rows


def _strip_local(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{k: v for k, v in row.items() if not k.startswith("_")} for row in rows]


async def execute_run(definition: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Execute every group of a run, storing each group's results as it finishes.

    Returns the ordered per-group transcript the analysis step consumes.
    """
    run_id = definition["run_id"]
    agent_id = definition.get("agent_id")
    user_id = definition.get("user_id")
    report_instructions = definition.get("report_instructions")
    groups = definition.get("query_groups") or []
    if not groups:
        logger.warning(f"[reports.runner] run {run_id} has no groups; nothing to do")
        return []

    # One shared query semaphore across all groups, so the cap bounds the run's TOTAL fan-out
    # rather than each group's separately.
    query_semaphore = asyncio.Semaphore(max(1, reports_env.REPORTS_MAX_CONCURRENT_QUERIES))
    group_semaphore = asyncio.Semaphore(max(1, reports_env.REPORTS_MAX_CONCURRENT_GROUPS))

    # Rows still owed to the database: groups whose mid-run flush failed, plus groups that
    # crashed outright. Swept at the end, and a failure there is fatal to the run — see below.
    unflushed: List[Dict[str, Any]] = []

    async def _run_group(group: Dict[str, Any]) -> List[Dict[str, Any]]:
        async with group_semaphore:
            if group.get("type") == "sequential":
                rows = await _run_sequential_group(
                    semaphore=query_semaphore,
                    run_id=run_id,
                    agent_id=agent_id,
                    user_id=user_id,
                    group=group,
                    report_instructions=report_instructions,
                )
            else:
                rows = await _run_independent_group(
                    semaphore=query_semaphore,
                    run_id=run_id,
                    agent_id=agent_id,
                    user_id=user_id,
                    group=group,
                    report_instructions=report_instructions,
                )
            # Store as soon as the group is done, so derived progress moves during the run and
            # a later crash cannot lose what already succeeded.
            try:
                await db_utils.upsert_results(run_id, _strip_local(rows))
            except Exception as e:
                # Don't abandon the rest of the run over one bad write — hand the rows to the
                # final sweep, which re-upserts them idempotently. They must not be silently
                # dropped: the answers exist, and a run reporting 'completed' without them
                # would be lying.
                logger.error(
                    f"[reports.runner] mid-run flush failed for group "
                    f"{group.get('group_id')} of run {run_id}: {e}",
                    exc_info=True,
                )
                unflushed.extend(rows)
            return rows

    outcomes = await asyncio.gather(
        *(_run_group(g) for g in groups), return_exceptions=True
    )

    transcript: List[Dict[str, Any]] = []
    for group, outcome in zip(groups, outcomes):
        if isinstance(outcome, BaseException):
            logger.error(
                f"[reports.runner] group {group.get('group_id')} crashed: {outcome}",
                exc_info=outcome,
            )
            # Record a failure row per query, so these count as failed rather than vanishing
            # and letting the run report 'completed' with answers quietly missing.
            rows = [
                _skipped_row(
                    query_id=q.get("query_id"),
                    group_id=group.get("group_id"),
                    reason=f"group execution failed: {outcome}",
                )
                | {"_question": q.get("text", "")}
                for q in (group.get("queries") or [])
            ]
            unflushed.extend(rows)
        else:
            rows = outcome
        transcript.append({
            "group_id": group.get("group_id"),
            "type": group.get("type", "independent"),
            "results": [
                {
                    "question": r.get("_question"),
                    "answer": r.get("answer"),
                    "error": r.get("error"),
                }
                for r in rows
            ],
        })

    if unflushed:
        # Whatever the per-group flushes did not manage to store. Deliberately NOT guarded: if
        # this fails the exception propagates, the executor marks the run `failed`, and the run
        # is honest about having results missing — far better than a `completed` run with holes
        # in it. The upsert is idempotent, so re-running is safe.
        logger.info(
            f"[reports.runner] final sweep: writing {len(unflushed)} outstanding row(s) "
            f"for run {run_id}"
        )
        await db_utils.upsert_results(run_id, _strip_local(unflushed))

    return transcript
