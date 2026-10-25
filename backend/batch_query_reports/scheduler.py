"""In-service scheduler for Batch Query Reports.

`run_due_reports()` is one tick: it claims every report whose `next_run_at` has passed
(atomically advancing each so it cannot double-fire), creates a `scheduled` run for each, and
dispatches it — the same pre-materialize → execute path as an on-demand run.

`run_scheduler_loop()` calls that tick on a fixed interval and is started by the API process
itself (see main.py), gated on REPORTS_SCHEDULER_ENABLED. No Celery Beat, cron or EventBridge
is involved.

Multi-instance safe: due reports are claimed with FOR UPDATE SKIP LOCKED in
`db_utils.claim_due_reports`, so when several replicas tick at the same moment each report is
claimed by exactly one of them.
"""
import asyncio
from datetime import datetime
from typing import Any, Dict

from logger import logger

from batch_query_reports import db_utils, executor


async def run_due_reports() -> Dict[str, Any]:
    """Fire every due report once. Returns a summary of what was triggered."""
    now = datetime.utcnow()
    due = await db_utils.claim_due_reports(now)
    triggered = []

    for report in due:
        report_id = report["report_id"]
        try:
            run = await db_utils.create_run(report_id, trigger="scheduled")
        except db_utils.QueryLimitExceeded as e:
            # The report grew past the cap (or the cap was lowered). Skip this occurrence; the
            # next_run_at has already advanced, so it will be retried on schedule once fixed.
            logger.warning(f"[reports.scheduler] skipping report {report_id}: {e}")
            continue
        except Exception as e:
            logger.error(f"[reports.scheduler] failed to create run for {report_id}: {e}")
            continue
        if not run:
            logger.warning(f"[reports.scheduler] report {report_id} vanished before run creation")
            continue

        await executor.start_run(run["run_id"])
        triggered.append({
            "report_id": report_id,
            "run_id": run["run_id"],
            "next_run_at": report["next_run_at"],
        })

    if triggered:
        logger.info(f"[reports.scheduler] triggered {len(triggered)} scheduled run(s)")
    return {
        "checked_at": now.isoformat(),
        "triggered_count": len(triggered),
        "triggered": triggered,
    }


async def run_scheduler_loop(interval_seconds: int) -> None:
    """Run `run_due_reports()` every `interval_seconds` until cancelled.

    A failing tick is logged and the loop continues — one bad tick must not stop the scheduler.
    """
    logger.info(f"[reports.scheduler] in-service scheduler started (interval={interval_seconds}s)")
    try:
        while True:
            try:
                await run_due_reports()
            except Exception:
                logger.exception("[reports.scheduler] tick failed")
            await asyncio.sleep(interval_seconds)
    except asyncio.CancelledError:
        logger.info("[reports.scheduler] in-service scheduler stopped")
        raise
