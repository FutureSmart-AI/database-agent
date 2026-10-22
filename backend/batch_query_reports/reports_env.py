"""Environment configuration for Batch Query Reports.

NL2SQL has no central `setup_env` module, so this is the one place report settings are read
from the environment. `main.py` loads the right `.env.<MODE>` before anything imports this,
so plain `os.getenv` is enough.

Variable names deliberately match the Agent Dashboard's (`REPORTS_*`) so ops can share one
config block between the two services.
"""
import os


def _flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    """Read an int, falling back to `default` on a blank or malformed value."""
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------

# Cap on the total number of queries one report may contain (summed across its groups).
# Every query is a full agent run, so an accidentally huge report is an accidentally large
# bill. Enforced on create/update AND at run creation, so it also applies to scheduled runs
# and to reports that already exceed a lowered limit. Per-agent overrides live in the
# `report_settings` table and win over this default.
REPORTS_MAX_QUERIES_PER_REPORT = _int("REPORTS_MAX_QUERIES_PER_REPORT", 20)

# Fan-out caps for the in-process executor. (The Celery path has its own caps, set worker-side
# via NL2SQL_REPORTS_MAX_CONCURRENT_*, because the worker owns that fan-out.) Either way a cap
# is needed: every query runs an agent pipeline holding a source-DB connection in an API
# process, so an unbounded report would starve interactive chat.
REPORTS_MAX_CONCURRENT_QUERIES = _int("REPORTS_MAX_CONCURRENT_QUERIES", 4)
REPORTS_MAX_CONCURRENT_GROUPS = _int("REPORTS_MAX_CONCURRENT_GROUPS", 2)
# How long one query may take before it is recorded as a failure (seconds). A batch query
# runs the same pipeline as chat but nobody is watching it, so it needs its own ceiling.
REPORTS_QUERY_TIMEOUT_SECONDS = _int("REPORTS_QUERY_TIMEOUT_SECONDS", 300)


# ---------------------------------------------------------------------------
# Executor: who actually runs the queries
# ---------------------------------------------------------------------------
# "celery" (default) — publish the run to the SQS queue the fs-agent-workers fleet consumes
#     and let it drive the run through the internal API (see router_internal), the same way
#     the Agent Dashboard's reports work. This is the default because report runs then
#     survive an API restart or deploy (the SQS message is redelivered), retries come from
#     Celery, and many runs can be in flight without occupying API request slots.
#     Requires the worker's NL2SQL_INTERNAL_BASE / NL2SQL_CHAT_BASE to point at this service.
# "inprocess" — this service runs the run itself, as a background asyncio task. No queue and
#     no worker needed, which is what makes it right for local development. A run in flight
#     does not survive a restart.
#
# NOTE: whichever is chosen, the agent work itself always happens HERE — the worker asks this
# service's own /v1/agents/{id}/chat per query. The queue moves the orchestration off this
# process, not the pipeline; NL2SQL replicas still do the work.
REPORTS_EXECUTOR = (os.getenv("REPORTS_EXECUTOR") or "celery").strip().lower()

# Base URL the in-process executor posts each query to. Defaults to this service's own
# loopback address, so a normal deployment needs no configuration: the run reuses the whole
# chat pipeline (sessions, logs, CSV export, charts) instead of duplicating it. The Celery path
# does the same thing from outside, via the worker's NL2SQL_CHAT_BASE.
REPORTS_CHAT_BASE = (
    os.getenv("REPORTS_CHAT_BASE")
    or f"http://127.0.0.1:{os.getenv('PORT', '8000')}/nl2sql/api"
)
# The master key the executor authenticates its own loopback calls with. Chat is
# agent-scoped, and a background run has no browser session to borrow.
FASTAPI_SECRET_KEY = os.getenv("FASTAPI_SECRET_KEY")


# ---------------------------------------------------------------------------
# Analysis (the optional report-level summary prompt)
# ---------------------------------------------------------------------------
# Plain summarization over the run transcript — no tools, no structured output — so a small
# model is the right default. Mirrors the `fallback` entry in model_config.json.
REPORTS_ANALYSIS_MODEL = os.getenv("REPORTS_ANALYSIS_MODEL", "gpt-5.4-mini")
REPORTS_ANALYSIS_MAX_TRANSCRIPT_CHARS = _int("REPORTS_ANALYSIS_MAX_TRANSCRIPT_CHARS", 60_000)


# ---------------------------------------------------------------------------
# In-service scheduler
# ---------------------------------------------------------------------------
# When enabled, the API process runs the "fire due reports" tick on a background loop.
# Safe to enable on every replica: due reports are claimed with FOR UPDATE SKIP LOCKED, so
# each one fires exactly once no matter how many replicas tick together.
REPORTS_SCHEDULER_ENABLED = _flag("REPORTS_SCHEDULER_ENABLED", "false")
REPORTS_SCHEDULER_INTERVAL_SECONDS = _int("REPORTS_SCHEDULER_INTERVAL_SECONDS", 60)


# ---------------------------------------------------------------------------
# Celery / SQS — only read when REPORTS_EXECUTOR=celery
# ---------------------------------------------------------------------------
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL")  # set in local mode; else built from creds
# Accept both spellings so this shares the worker's and the dashboard's config blocks.
SQS_AWS_ACCESS_KEY = os.getenv("SQS_AWS_ACCESS_KEY_ID") or os.getenv("SQS_AWS_ACCESS_KEY")
SQS_AWS_SECRET_KEY = os.getenv("SQS_AWS_SECRET_ACCESS_KEY") or os.getenv("SQS_AWS_SECRET_KEY")
SQS_AWS_REGION = os.getenv("SQS_AWS_REGION", "us-east-1")
REPORTS_QUEUE_URL = os.getenv("REPORTS_QUEUE_URL")
# A predefined-queue NAME must equal its URL tail (and end in `.fifo` for FIFO queues), so
# derive it from the URL rather than from the unrelated ingestion queue name.
if os.getenv("REPORTS_QUEUE_NAME"):
    REPORTS_QUEUE_NAME = os.getenv("REPORTS_QUEUE_NAME")
elif REPORTS_QUEUE_URL:
    REPORTS_QUEUE_NAME = REPORTS_QUEUE_URL.rstrip("/").split("/")[-1]
else:
    REPORTS_QUEUE_NAME = "file-indexer"
# The worker task that executes NL2SQL runs. NOT `process_report_run` — that one is the
# dashboard's and would fetch the definition from the dashboard, which has never heard of this
# run. Both services mint `run_<32hex>` ids, so the task name is the only thing that tells the
# worker whose run it is.
REPORTS_TASK_NAME = os.getenv("REPORTS_TASK_NAME", "workers.tasks.process_nl2sql_report_run")
