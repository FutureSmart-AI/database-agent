"""Dispatch a created run to whoever will execute it, and drive the in-process path.

`start_run` is the single entry point every caller uses — the on-demand endpoint, the
`run_immediately` flag on create, and the scheduler tick — so all three paths behave
identically.

Which executor runs depends on `REPORTS_EXECUTOR`:
- `celery` (default): the run is published to the `fs-agent-workers` fleet as
  `workers.tasks.process_nl2sql_report_run`, and the worker drives it through the internal API.
  Falls back to in-process when no broker is configured, so a missing queue delays nothing and
  local development needs no SQS.
- `inprocess`: the run executes here as a background asyncio task.

Either way the agent work happens in this service — the worker calls this service's own
`/v1/agents/{id}/chat` per query. What the queue buys is durability (a run survives an API
restart, because the SQS message is redelivered) and keeping orchestration off the API process.
"""
import asyncio
from datetime import datetime
from typing import Optional, Set

from logger import logger

from batch_query_reports import analysis, db_utils, queue_utils, reports_env, runner

# Strong references to the in-flight run tasks. asyncio only holds a weak reference to a task,
# so without this a run could be garbage-collected mid-execution. Also gives shutdown something
# to cancel.
_running_tasks: Set[asyncio.Task] = set()


def _track(task: asyncio.Task) -> None:
    _running_tasks.add(task)
    task.add_done_callback(_running_tasks.discard)


def in_flight_count() -> int:
    """How many runs this process is currently executing (exposed for diagnostics)."""
    return len(_running_tasks)


async def start_run(run_id: str) -> str:
    """Start executing `run_id`. Returns the dispatch mode actually used.

    Returns before the run finishes — reports are asynchronous by design; callers poll
    `.../runs/{run_id}/status`.
    """
    if reports_env.REPORTS_EXECUTOR == "celery":
        if queue_utils.broker_configured():
            # send_task does blocking network I/O, so keep it off the event loop.
            sent = await asyncio.to_thread(queue_utils.enqueue_run, run_id)
            if sent:
                return "queued"
            logger.warning(
                f"[reports.executor] enqueue failed for run {run_id}; "
                f"executing in-process instead"
            )
        else:
            logger.warning(
                "[reports.executor] REPORTS_EXECUTOR=celery but no broker is configured; "
                f"executing run {run_id} in-process instead"
            )

    _track(asyncio.create_task(execute_run_task(run_id), name=f"report-run-{run_id}"))
    return "started"


async def execute_run_task(run_id: str) -> None:
    """Drive one run start-to-finish: running → queries → analysis → completed.

    Never raises to its caller (it is a detached task). Any failure that reaches here closes the
    run out as `failed` with a reason, because a run left `running` forever is the one outcome a
    polling client cannot recover from.
    """
    try:
        definition = await db_utils.get_run_definition(run_id)
        if not definition:
            logger.error(f"[reports.executor] run {run_id} not found; nothing to execute")
            return

        status = await db_utils.update_run_status(
            run_id, "running", started_at=datetime.utcnow()
        )
        # A run cancelled while it was still pending is already terminal — update_run_status
        # refused the transition and returned that state. Don't execute it.
        if status != "running":
            logger.info(
                f"[reports.executor] run {run_id} is '{status}' before execution; skipping"
            )
            return

        logger.info(
            f"[reports.executor] executing run {run_id} "
            f"(agent={definition.get('agent_id')}, groups={len(definition.get('query_groups') or [])})"
        )
        transcript = await runner.execute_run(definition)

        analysis_prompt = definition.get("analysis_prompt")
        if analysis_prompt and transcript:
            summary: Optional[str] = await analysis.run_analysis(analysis_prompt, transcript)
            if summary:
                await db_utils.set_run_analysis(run_id, summary)
            else:
                # Not fatal: the per-query results are the substance of the report.
                logger.warning(
                    f"[reports.executor] no analysis summary produced for run {run_id}"
                )

        # A no-op when the run was cancelled meanwhile — the cancel stands.
        await db_utils.update_run_status(run_id, "completed", ended_at=datetime.utcnow())
        logger.info(f"[reports.executor] completed run {run_id}")

    except asyncio.CancelledError:
        # The process is shutting down mid-run. Try to close the run out so it isn't left
        # `running` forever; shielded because the task is already being cancelled.
        logger.warning(f"[reports.executor] run {run_id} cancelled (shutdown)")
        try:
            await asyncio.shield(db_utils.update_run_status(
                run_id,
                "failed",
                ended_at=datetime.utcnow(),
                failure_reason="execution interrupted by service shutdown",
            ))
        except Exception:
            logger.error(f"[reports.executor] could not mark cancelled run {run_id} as failed")
        raise
    except Exception as e:
        logger.error(f"[reports.executor] run {run_id} failed: {e}", exc_info=True)
        try:
            await db_utils.update_run_status(
                run_id,
                "failed",
                ended_at=datetime.utcnow(),
                failure_reason=str(e)[:500],
            )
        except Exception as inner:
            logger.error(
                f"[reports.executor] also failed to mark run {run_id} as failed: {inner}"
            )
