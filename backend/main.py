import sys, os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from sys import platform
from dotenv import load_dotenv
import os

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# # from auth.router import authentication
# from session.router import chatbot_sessions
from runtime_config import load_environment
load_environment()
current_server = os.getenv("SERVER")

if platform == "linux" and current_server == "PROD":
    __import__('pysqlite3')
    import sys
    sys.modules['sqlite3'] = sys.modules.pop('pysqlite3')

from swaggers.chart import chart_docs_app
from swaggers.csv import csv_docs_app
from swaggers.nl2sql import nl2sql_docs_app

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
from starlette.middleware.sessions import SessionMiddleware
import time
from logger import logger
from otel_tracing import SmartTracingMiddleware

app = FastAPI(
    title="FutureSmart Agents Platform — NL2SQL, CSV & Graph APIs",
    description=(
        "Unified API for the FutureSmart Agents Platform covering: "
        "NL2SQL (natural-language → SQL and chat/query endpoints), "
        "CSV utilities (ingest, preview, transform), and "
        "Graph & Visualization services (mapping, assembly, visualizations). "
        "Includes agent management, database introspection, few-shot examples, and developer utilities."
    ),
    root_path=None,
    docs_url=None,
    redoc_url=None,
    openapi_url=None
)

try:
    import prometheus_fastapi_instrumentator.routing as _prom_routing
    _orig_get_route_name = _prom_routing.get_route_name
    def _safe_get_route_name(request):
        try:
            return _orig_get_route_name(request)
        except AttributeError:
            return None
    _prom_routing.get_route_name = _safe_get_route_name
except Exception:
    pass

Instrumentator(should_group_untemplated=True).instrument(app)
from langsmith.middleware import TracingMiddleware
app.add_middleware(TracingMiddleware)

# Add the CORSMiddleware to enable Cross-Origin Resource Sharing
app.add_middleware(
    CORSMiddleware,
    allow_origins=([os.getenv("STANDALONE_ORIGIN", "http://localhost:3001")]
                   if os.getenv("MODE", "").lower() == "standalone" else ["*"]),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add the SessionMiddleware to enable session handling
app.add_middleware(
    SessionMiddleware, secret_key=os.getenv("FASTAPI_SECRET_KEY"),
    **({"session_cookie": "database_agent_session", "max_age": 8 * 60 * 60,
        "https_only": os.getenv("STANDALONE_COOKIE_SECURE", "false").lower() == "true"}
       if os.getenv("MODE", "").lower() == "standalone" else {}),
)
app.add_middleware(SmartTracingMiddleware)
@app.middleware("http")
async def log_response_time(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    logger.info(f"Request: {request.url.path} completed in {process_time:.4f} seconds")
    return response 

_reports_scheduler_task = None


@app.on_event("startup")
async def on_startup():
    logger.info("Multi(csv,graph,nl2sql) Agents app startup complete, ready to accept requests")

    # Batch Query Reports: fire scheduled reports from inside this process, so the feature needs
    # no Celery Beat, cron or EventBridge. Safe on every replica — due reports are claimed with
    # FOR UPDATE SKIP LOCKED, so each one fires exactly once. Off unless REPORTS_SCHEDULER_ENABLED.
    global _reports_scheduler_task
    from batch_query_reports import reports_env
    from batch_query_reports.scheduler import run_scheduler_loop

    if reports_env.REPORTS_SCHEDULER_ENABLED:
        import asyncio
        _reports_scheduler_task = asyncio.create_task(
            run_scheduler_loop(reports_env.REPORTS_SCHEDULER_INTERVAL_SECONDS)
        )
    else:
        logger.info(
            "[reports.scheduler] in-service scheduler disabled (REPORTS_SCHEDULER_ENABLED=false)"
        )


@app.on_event("shutdown")
async def on_shutdown():
    """Stop the reports scheduler cleanly, so a reload doesn't leave a tick loop behind."""
    global _reports_scheduler_task
    if _reports_scheduler_task:
        import asyncio
        _reports_scheduler_task.cancel()
        try:
            await _reports_scheduler_task
        except asyncio.CancelledError:
            pass
        _reports_scheduler_task = None



@app.get("/health", include_in_schema=False, status_code=status.HTTP_200_OK)
async def health(request: Request):
    """
    Health check endpoint for deployment systems
    This endpoint is not included in the API documentation
    Logs the caller info to help debug ALB/target-group health checks.
    """
    logger.info(f"Health check from: {request.client.host if request.client else 'unknown'}")
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"status": "ok", "service": "Multi(csv,graph,nl2sql) Agents"}
    )

# Mount graph and csv mini-apps (each exposes its own /docs and /openapi.json)
app.mount("/chart/api", chart_docs_app)
app.mount("/csv/api", csv_docs_app)
app.mount("/nl2sql/api", nl2sql_docs_app)




if __name__ == "__main__":
    import uvicorn

    # Get port from environment variable or use default
    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")

    logger.info(f"Starting NL2SQL API server on {host}:{port}")

    # Run the FastAPI application
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info"
    )
