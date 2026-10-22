"""Pure schedule math for Batch Query Reports.

`compute_next_run_at` maps a report's `schedule` config to the next run time in **naive UTC**,
matching how the run timestamp columns are stored. Kept free of any db/queue import so it can
be used from anywhere without a circular import.

Schedule shape (only `frequency` is required):
    {"frequency": "daily" | "weekly" | "monthly" | "cron", "cron": "*/5 * * * *", "timezone": "UTC"}
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from dateutil.relativedelta import relativedelta

try:  # py3.9+
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None

from logger import logger


def _naive_utc(dt: datetime) -> datetime:
    """Drop tzinfo, normalizing to UTC first when aware."""
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def compute_next_run_at(
    schedule: Optional[Dict[str, Any]],
    base: Optional[datetime] = None,
) -> Optional[datetime]:
    """Return the next run time (naive UTC) after `base`, or None if not schedulable.

    `base` defaults to now. Fixed frequencies are simply `base + interval`; cron is the next
    matching instant at or after `base`, evaluated in the schedule's timezone. Returns None
    for an absent or unrecognized schedule, and for `cron` with no expression.
    """
    if not schedule:
        return None

    base = _naive_utc(base) if base else datetime.utcnow()
    frequency = (schedule.get("frequency") or "").lower()

    if frequency == "daily":
        return base + timedelta(days=1)
    if frequency == "weekly":
        return base + timedelta(weeks=1)
    if frequency == "monthly":
        return base + relativedelta(months=1)
    if frequency == "cron":
        cron = schedule.get("cron")
        if not cron:
            logger.warning("[reports.schedule] cron frequency with no expression — not scheduling")
            return None
        return _next_cron(cron, base, schedule.get("timezone") or "UTC")

    logger.warning(f"[reports.schedule] unknown frequency '{frequency}' — not scheduling")
    return None


def _next_cron(cron: str, base_utc: datetime, tz_name: str) -> Optional[datetime]:
    """Next cron occurrence after `base_utc`, returned as naive UTC.

    croniter is imported lazily so a deployment that never uses cron schedules does not need
    it installed, and a missing/invalid expression degrades to "not scheduled" instead of
    breaking the request that saved the report.
    """
    try:
        from croniter import croniter
    except Exception:  # pragma: no cover
        logger.error("[reports.schedule] croniter not installed — cannot evaluate cron schedules")
        return None

    try:
        tz = ZoneInfo(tz_name) if ZoneInfo else timezone.utc
    except Exception:
        logger.warning(f"[reports.schedule] unknown timezone '{tz_name}', falling back to UTC")
        tz = timezone.utc

    try:
        base_local = base_utc.replace(tzinfo=timezone.utc).astimezone(tz)
        nxt = croniter(cron, base_local).get_next(datetime)  # tz-aware, in `tz`
        return _naive_utc(nxt)
    except Exception as e:
        logger.error(f"[reports.schedule] invalid cron '{cron}': {e}")
        return None


def validate_cron(cron: str) -> bool:
    """True when `cron` is an expression croniter accepts.

    Used by the router to reject a bad expression at save time rather than silently leaving
    the report unscheduled. Returns True when croniter is unavailable — refusing to save on a
    missing optional dependency would be worse than accepting an unverified expression.
    """
    try:
        from croniter import croniter
    except Exception:  # pragma: no cover
        return True
    return bool(croniter.is_valid(cron))
