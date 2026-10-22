from fastapi import FastAPI
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from otel_tracing import SubAppRouteMiddleware

from csv_agent.api.csv_api import router as csv_agent_router

fastapi_metadata = [
    {
        "name": "CSV Agent",
        "description": "APIs for the CSV Agent (CSV ingestion and utilities)"
    }
]

# Mini app that only exposes csv routes and documentation
csv_docs_app = FastAPI(openapi_tags=fastapi_metadata)
csv_docs_app.add_middleware(SubAppRouteMiddleware, mount_prefix="/csv/api")
csv_docs_app.include_router(csv_agent_router, tags=["CSV Agent"])

@csv_docs_app.get("/docs", include_in_schema=False)
async def csv_swagger_ui():
    return get_swagger_ui_html(
        openapi_url="./openapi.json",
        title="CSV Agent API",
    )

@csv_docs_app.get("/openapi.json", include_in_schema=False)
async def csv_openapi_json():
    return get_openapi(
        title="CSV Agent API",
        description="CSV agent endpoints",
        routes=csv_docs_app.routes,
    )

@csv_docs_app.get("/health", include_in_schema=False)
async def csv_health():  
    return {"status": "ok", "service": "csv"}