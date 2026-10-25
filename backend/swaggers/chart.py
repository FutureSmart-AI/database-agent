from fastapi import FastAPI
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from otel_tracing import SubAppRouteMiddleware


from chart_agent.api.chart_api import router as chart_agent_router

fastapi_metadata = [
    {
        "name": "Chart Agent",
        "description": "APIs for the Chart Agent (visualization, mapping, assembly)"
    }
]

# Mini app that only exposes chart routes and documentation
chart_docs_app = FastAPI(openapi_tags=fastapi_metadata)
chart_docs_app.add_middleware(SubAppRouteMiddleware, mount_prefix="/chart/api")

chart_docs_app.include_router(chart_agent_router, tags=["Chart Agent"])

@chart_docs_app.get("/docs", include_in_schema=False)
async def chart_swagger_ui():  
    return get_swagger_ui_html(
        openapi_url="./openapi.json",
        title="Graph Agent API",
    )

@chart_docs_app.get("/openapi.json", include_in_schema=False)
async def chart_openapi_json():  
    return get_openapi(
        title="Chart Agent API",
        description="Chart agent endpoints (visualization/mapping)",
        routes=chart_docs_app.routes,
    )

@chart_docs_app.get("/health", include_in_schema=False)
async def chart_health(): 
    return {"status": "ok", "service": "chart"}  