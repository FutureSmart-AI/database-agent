"""Celery producer for the external-worker execution path (REPORTS_EXECUTOR=celery).

Only used when a run is handed to the `fs-agent-workers` fleet instead of being executed here.
That fleet is a Celery consumer with an **SQS broker** (`Celery('file_indexer')`,
JSON-serialized, tasks named `workers.tasks.*`), so a raw JSON blob dropped on the queue would
never deserialize — we must publish a proper Celery task message:

    send_task("workers.tasks.process_report_run", kwargs={"run_id": ...}, queue=<queue>)

The task carries only the `run_id`; the worker then fetches the definition from
`GET /internal/runs/{run_id}` and posts results back. For that to reach THIS service, the
worker's `DASHBOARD_INTERNAL_BASE` must point at this service's `/nl2sql/api` — it defaults to
the Agent Dashboard, which knows nothing about a run created here.

Best-effort by design: enqueue never raises. A run that fails to publish stays `pending` and
can be re-enqueued, which is strictly better than a 500 on a report the user already created.
"""
import urllib.parse

from logger import logger

from batch_query_reports import reports_env

_celery_app = None


def broker_configured() -> bool:
    """Whether a broker is configured at all — checked before claiming this path can work."""
    return bool(reports_env.REPORTS_QUEUE_URL or reports_env.CELERY_BROKER_URL)


def _broker_url() -> str:
    """Mirror the worker: URL-encoded credentials embedded in the sqs:// broker URL.

    An explicit CELERY_BROKER_URL wins (local mode points at a local broker directly).
    """
    if reports_env.CELERY_BROKER_URL:
        return reports_env.CELERY_BROKER_URL
    if reports_env.SQS_AWS_ACCESS_KEY and reports_env.SQS_AWS_SECRET_KEY:
        secret = urllib.parse.quote(reports_env.SQS_AWS_SECRET_KEY, safe="")
        return (
            f"sqs://{reports_env.SQS_AWS_ACCESS_KEY}:{secret}"
            f"@sqs.{reports_env.SQS_AWS_REGION}.amazonaws.com/"
        )
    return "sqs://"


def _get_app():
    """Lazily build a Celery producer app matching the worker's broker config.

    Lazy on purpose: `celery` is only needed for this path, so a deployment using the
    in-process executor does not have to install it.
    """
    global _celery_app
    if _celery_app is not None:
        return _celery_app

    from celery import Celery

    queue = reports_env.REPORTS_QUEUE_NAME
    app = Celery("fs_agent_nl2sql_producer")
    app.conf.broker_url = _broker_url()
    app.conf.task_serializer = "json"
    app.conf.accept_content = ["json"]
    app.conf.result_serializer = "json"
    app.conf.result_backend = None  # producer only; we never wait on a result
    app.conf.task_default_queue = queue
    app.conf.task_routes = {"workers.tasks.*": {"queue": queue}}

    # These mirror the worker's celery_workers/config.py; a mismatch here shows up as messages
    # that publish successfully and are never consumed.
    transport_options = {
        "region": reports_env.SQS_AWS_REGION,
        "is_secure": True,
        "visibility_timeout": 3600,
        "polling_interval": 1,
    }
    if reports_env.REPORTS_QUEUE_URL:
        queue_conf = {"url": reports_env.REPORTS_QUEUE_URL}
        if reports_env.SQS_AWS_ACCESS_KEY and reports_env.SQS_AWS_SECRET_KEY:
            # NOTE: the worker uses access_key/secret_key, not kombu's *_id/_access spelling.
            queue_conf["access_key"] = reports_env.SQS_AWS_ACCESS_KEY
            queue_conf["secret_key"] = reports_env.SQS_AWS_SECRET_KEY
        transport_options["predefined_queues"] = {queue: queue_conf}
    app.conf.broker_transport_options = transport_options

    _celery_app = app
    return app


def enqueue_run(run_id: str) -> bool:
    """Publish a Celery task for `run_id`. Returns True if sent, False otherwise."""
    queue = reports_env.REPORTS_QUEUE_NAME
    if not broker_configured():
        logger.warning(
            f"[reports.queue] No SQS broker configured (REPORTS_QUEUE_URL/CELERY_BROKER_URL) — "
            f"run {run_id} not enqueued (stays pending)."
        )
        return False

    try:
        send_kwargs = dict(
            name=reports_env.REPORTS_TASK_NAME,
            kwargs={"run_id": run_id},
            queue=queue,
        )
        # FIFO queues: one message group per run so runs aren't serialized behind each other,
        # plus an explicit dedup id guarding an accidental double-publish.
        if str(queue).endswith(".fifo"):
            send_kwargs["MessageGroupId"] = run_id
            send_kwargs["MessageDeduplicationId"] = run_id

        _get_app().send_task(**send_kwargs)
        logger.info(
            f"[reports.queue] Enqueued {reports_env.REPORTS_TASK_NAME}(run_id={run_id}) -> '{queue}'"
        )
        return True
    except Exception as e:
        logger.error(f"[reports.queue] Failed to enqueue run {run_id}: {e}")
        return False
