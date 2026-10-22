"""Batch Query Reports for NL2SQL.

Run a batch of natural-language questions against an NL2SQL agent in the background and
retrieve one structured report (per-query answers + executed SQL + an optional LLM summary).

The feature mirrors the Agent Dashboard's `batch_query_reports` contract (see that service's
`docs/batch-query-reports-spec.md`) so the two are comparable: NL2SQL owns its own tables in its
own database, and runs are executed by the same `fs-agent-workers` Celery fleet, on their own
task (`workers.tasks.process_nl2sql_report_run`). The difference is who answers a query — the
worker asks THIS service's `/v1/agents/{id}/chat`, because the chat service 404s on agents
NL2SQL created. An `inprocess` executor is also available for local development.
See docs/nl2sql/batch-query-reports.md.

Modules:
    reports_env             environment configuration (limits, executor, scheduler, queue)
    pydantic_model_db       SQLModel tables this service owns
    pydantic_models_restful request/response models
    db_utils                all database access; derives progress from stored results
    schedule_utils          pure schedule math (next_run_at)
    scheduler               in-service "fire due reports" tick + loop
    chat_client             calls this service's own /v1/agents/{id}/chat per query
    runner                  execution semantics (independent parallel, sequential in-order)
    analysis                the optional report-level analysis prompt
    executor                dispatch: run in-process, or enqueue to the Celery worker fleet
    queue_utils             Celery producer for the external-worker path
    exporters               on-demand Markdown / JSON / CSV rendering
    dependencies            internal (service-to-service) auth
    router_restful          public, user-facing API
    router_internal         internal API for an external worker
"""
