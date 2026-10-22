from fastapi import FastAPI
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from otel_tracing import SubAppRouteMiddleware

from batch_query_reports.router_internal import router as reports_internal_router
from batch_query_reports.router_restful import router as reports_router

from api.v1.routers import (
    agents_router,
    api_keys_router,
    config_router,
    databases_router,
    databases_fewshot_router,
    databases_tables_router,
    databases_hc_router,
    chat_router,
    feedback_router,
    invitations_router,
    statistics_router,
    analytics_router,
    credentials_router,
    owner_config_router,
    usage_events_router,
    utility_router,
    sessions_router,
    service_router,
    widgets_router,
)

fastapi_metadata = [
    {
        "name": "NL2SQL Agents Resource",
        "description": "Create, read, update, and delete NL2SQL agents"
    },
    # {
    #     "name": "Agent Configuration",
    #     "description": "Manage agent configuration including node-level LLM settings and agent parameters"
    # },
    {
        "name": "Databases (Multi-DB)",
        "description": "Manage an agent's multiple source databases: CRUD, test, RDS discovery, bulk import, status check, and auto-generate description"
    },
    {
        "name": "Tables (per-DB)",
        "description": "Per-database table descriptions and visibility (scoped by db_id)"
    },
    {
        "name": "Column Descriptions (per-DB)",
        "description": "Per-database column descriptions (scoped by db_id)"
    },
    {
        "name": "Few-Shot Examples (per-DB)",
        "description": "Per-database few-shot examples (scoped by db_id)"
    },
    {
        "name": "High Cardinality Columns (per-DB)",
        "description": "Per-database manual high-cardinality column registration (scoped by db_id)"
    },
    {
        "name": "HC Column Profiling (per-DB)",
        "description": "Per-database automatic high-cardinality profiling (scoped by db_id)"
    },
    {
        "name": "Chat & Messages",
        "description": "Send chat messages and retrieve message history"
    },
    {
        "name": "Feedback",
        "description": "Submit feedback on agent responses"
    },
    {
        "name": "Statistics",
        "description": "Get agent usage statistics and analytics"
    },
    {
        "name": "Analytics",
        "description": "Agent Health & Analytics: per-agent scorecard, failures, trends, per-query drill-down and LangSmith cost sync"
    },
    {
        "name": "Owner Credentials",
        "description": (
            "Bring-your-own-key storage: an owner's provider API keys, validated with the "
            "provider and stored encrypted, so their model usage bills to their own account "
            "instead of the platform's. Keys are returned masked."
        )
    },
    {
        "name": "Owner Configuration",
        "description": (
            "Per-owner NL2SQL settings: tier, the caps this service can enforce "
            "(agents, monthly LLM tokens, team members) and whether NL2SQL is enabled for "
            "them. Reads fall back to defaults when an owner has no stored row; writes "
            "require the master key."
        )
    },
    {
        "name": "Usage Events",
        "description": (
            "Owner-level usage: one row per billable operation (LLM call, SQL execution, "
            "chart generation) with its tokens, durations and row counts. Query raw events, "
            "aggregate them by agent/operation/key type, or roll them up per owner. Distinct "
            "from Analytics, which is per-query and per-agent."
        )
    },
    {
        "name": "Utility",
        "description": "System utilities including models, health check, and metrics"
    },
    {
        "name": "Service Validation",
        "description": "NL2SQL service validation endpoints for Agent Registry integration"
    },
    {
        "name": "API Keys",
        "description": "Issue, list, and revoke per-agent API keys. A key authenticates only its own agent, via the X-API-Key header."
    },
    {
        "name": "Widget Settings",
        "description": "Per-agent widget appearance. Reading is the one endpoint an anonymous embed can reach, gated on the agent's own is_public/allowed_domains."
    },
    {
        "name": "Batch Query Reports",
        "description": (
            "Run a batch of questions against an agent in the background and retrieve one "
            "structured report. A report is a reusable definition (query groups, optional "
            "instructions, analysis prompt and schedule); each execution creates a run, and all "
            "runs are retained so results can be compared over time."
        )
    }
]



# Mini app that only exposes the main nl2sql routes and documentation
nl2sql_docs_app = FastAPI(openapi_tags=fastapi_metadata)
nl2sql_docs_app.add_middleware(SubAppRouteMiddleware, mount_prefix="/nl2sql/api")

nl2sql_docs_app.include_router(agents_router, tags=["NL2SQL Agents Resource"])
nl2sql_docs_app.include_router(databases_router, tags=["Databases (Multi-DB)"])
# Per-DB metadata routers — each carries its own per-route tags so they appear under their
# own Swagger sections (Tables / Column Descriptions / Few-Shot / High Cardinality), not all
# lumped under "Databases (Multi-DB)". databases_hc must precede databases_tables so its static
# /tables/hc-profile and /tables/high-cardinality-columns paths aren't captured by the
# dynamic /tables/{table_name} routes.
nl2sql_docs_app.include_router(databases_hc_router)
nl2sql_docs_app.include_router(databases_tables_router)
nl2sql_docs_app.include_router(databases_fewshot_router, tags=["Few-Shot Examples (per-DB)"])
nl2sql_docs_app.include_router(chat_router, tags=["Chat & Messages"])
nl2sql_docs_app.include_router(feedback_router, tags=["Feedback"])
nl2sql_docs_app.include_router(statistics_router, tags=["Statistics"])
nl2sql_docs_app.include_router(analytics_router, tags=["Analytics"])
nl2sql_docs_app.include_router(credentials_router, tags=["Owner Credentials"])
nl2sql_docs_app.include_router(owner_config_router, tags=["Owner Configuration"])
nl2sql_docs_app.include_router(usage_events_router, tags=["Usage Events"])
nl2sql_docs_app.include_router(utility_router, tags=["Utility"])
nl2sql_docs_app.include_router(service_router, tags=["Service Validation"])
nl2sql_docs_app.include_router(config_router, tags=["Agent Configuration"])
nl2sql_docs_app.include_router(sessions_router, tags=["Sessions"])
nl2sql_docs_app.include_router(api_keys_router, tags=["API Keys"])
nl2sql_docs_app.include_router(invitations_router, tags=["Agent Invitations"])
nl2sql_docs_app.include_router(widgets_router, tags=["Widget Settings"])
nl2sql_docs_app.include_router(reports_router, tags=["Batch Query Reports"])
# Worker-facing: master key only, and hidden from the schema — see router_internal.py.
nl2sql_docs_app.include_router(reports_internal_router, include_in_schema=False)


@nl2sql_docs_app.get("/docs", include_in_schema=False)
async def nl2sql_swagger_ui():
    return get_swagger_ui_html(
        # Use a relative OpenAPI URL so the UI works regardless of the mount path
        openapi_url="/nl2sql/api/openapi.json",
        title="NL2SQL API",
    )


@nl2sql_docs_app.get("/openapi.json", include_in_schema=False)
async def nl2sql_openapi_json():
    return get_openapi(
        title="NL2SQL API",
        description="NL2SQL main endpoints",
        routes=nl2sql_docs_app.routes,
    )

@nl2sql_docs_app.get("/health", include_in_schema=False)
async def nl2sql_health():
    return {"status": "ok", "service": "nl2sql"}


# Local login routes are inert unless MODE=standalone.
from standalone.auth import router as standalone_auth_router
nl2sql_docs_app.include_router(standalone_auth_router)
