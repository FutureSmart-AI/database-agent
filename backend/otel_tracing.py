from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from contextvars import ContextVar
import functools, inspect, os, re
from logger import logger

# Use environment variables with defaults to avoid NoneType issues during initialization
SERVICE_ROUTE_MAP = {
    "/csv/api":    os.getenv("OTEL_SERVICE_NAME_CSV"),
    "/chart/api":  os.getenv("OTEL_SERVICE_NAME_CHART"),
    "/nl2sql/api": os.getenv("OTEL_SERVICE_NAME_NL2SQL"),
}

_EMAIL_RE = re.compile(r"/[^/@\s]+@[^/\s]+")
_HEX_ID_RE = re.compile(r"/[0-9a-f]{24,}(?=/|$)", re.IGNORECASE)
_UUID_RE = re.compile(
    r"/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?=/|$)",
    re.IGNORECASE,
)
# Catches /agents/<anything> → /agents/{agent_id}
# Matches patterns like NL2SQL_FC9A5984, CSV_A1B2, etc.
_AGENT_ID_RE = re.compile(r"/agents/[A-Z0-9_]+(?=/|$)", re.IGNORECASE)

# Patterns to exclude from tracing for background tasks
_EXCLUDED_TRACE_PATTERNS = ["/health", "/metrics", "/docs", "/openapi.json"]


def _normalize_path(path: str) -> str:
    # 1. Parameterize agent IDs: /agents/NL2SQL_ABC123 → /agents/{agent_id}
    path = _AGENT_ID_RE.sub("/agents/{agent_id}", path)
    # 2. Replace UUIDs
    path = _UUID_RE.sub("/{id}", path)
    # 3. Replace long hex IDs
    path = _HEX_ID_RE.sub("/{id}", path)
    # 4. Replace email-like segments
    path = _EMAIL_RE.sub("/{user_id}", path)
    return path


def normalize_prometheus_handler_metrics(info) -> None:
    """Low-cardinality `handler` label for prometheus-fastapi-instrumentator."""
    h = getattr(info, "modified_handler", None)
    if not isinstance(h, str) or h == "none" or not h.startswith("/"):
        return
    h = _normalize_path(h)
    req = getattr(info, "request", None)
    if req is not None:
        scope = getattr(req, "scope", None)
        if isinstance(scope, dict):
            raw = _canonical_http_path(scope)
            if "{" not in h:
                h = raw
    info.modified_handler = _normalize_path(h)


def _canonical_http_path(scope: dict) -> str:
    """Rebuild full path for routing + labels when behind a proxy or stripped mount."""
    raw = (scope.get("path") or "").split("?")[0]
    root = (scope.get("root_path") or "").rstrip("/")
    if root and not raw.startswith(root):
        full = root + (raw if raw.startswith("/") else "/" + raw)
    else:
        full = raw
    if full.startswith(("/nl2sql/api", "/csv/api", "/chart/api")):
        return full
    if raw.startswith("/v1/agents/") or (raw.startswith("/v1/") and "/agents/" in raw):
        return "/nl2sql/api" + raw if raw.startswith("/") else "/nl2sql/api/" + raw
    return full


# ─────────────────────────────────────────────────────────────────────────────
# SubAppRouteMiddleware
#
# Add this to each mounted sub-app (nl2sql_docs_app, csv_docs_app, chart_docs_app).
# Because scope["route"] is only populated INSIDE the sub-app after FastAPI
# resolves routing, this middleware reads the resolved route template and writes
# it into scope["_resolved_route_template"] so SmartTracingMiddleware (running
# at the outer app level) can call span.update_name with the correct template.
# ─────────────────────────────────────────────────────────────────────────────
class SubAppRouteMiddleware:
    def __init__(self, app, mount_prefix: str):
        """
        mount_prefix: the path the sub-app is mounted at in the parent app.
                      e.g. "/nl2sql/api", "/csv/api", "/chart/api"
        """
        self.app = app
        self.mount_prefix = mount_prefix.rstrip("/")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        await self.app(scope, receive, send)

        # After the sub-app runs, scope["route"] is now populated by FastAPI.
        route = scope.get("route")
        if route is not None:
            raw_template = getattr(route, "path", None)
            if raw_template:
                # Re-attach the mount prefix stripped by FastAPI's mount logic,
                # then normalize to replace any raw IDs.
                full_template = self.mount_prefix + raw_template
                scope["_resolved_route_template"] = _normalize_path(full_template)


# Stores the active tracer for the current request context
_current_tracer: ContextVar = ContextVar("current_tracer", default=None)


def _get_endpoint():
    return os.getenv("OTEL_EXPORTER_ENDPOINT")


def _create_private_tracer(service_name: str):
    if not service_name:
        service_name = "fs-agent-service"
    
    endpoint = _get_endpoint()
    if not endpoint:
        logger.warning(f"OTEL_EXPORTER_ENDPOINT not set. Skipping OTel tracer for {service_name}")
        return trace.get_tracer(service_name)
    
    try:
        resource = Resource.create({"service.name": str(service_name)})
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
        )
        return provider.get_tracer(service_name or __name__)
    except Exception as e:
        logger.error(f"Failed to initialize OTel tracer for {service_name}: {e}")
        return trace.get_tracer(service_name or __name__)


class SmartTracingMiddleware:
    def __init__(self, app):
        self.app = app
        self._tracers = {
            service: _create_private_tracer(service)
            for service in SERVICE_ROUTE_MAP.values()
        }

    def _should_trace_path(self, path: str, headers: dict = None) -> bool:
        """Check if path should be traced or filtered out.
        
        Filters are only applied if X-Internal=background header is present,
        indicating a background task call. Direct API calls are always traced.
        """
        path_lower = path.lower()
        
        # Check for X-Internal header indicating background task
        if headers:
            x_internal = headers.get("x-internal") or headers.get("X-Internal")
            if x_internal and x_internal.lower() == "background":
                # This is a background task - check if it should be filtered
                for pattern in _EXCLUDED_TRACE_PATTERNS:
                    if pattern in path_lower:
                        return False
        
        return True

    def _resolve(self, path: str):
        for prefix, service in SERVICE_ROUTE_MAP.items():
            if path.startswith(prefix):
                return self._tracers[service], service
        return None, None

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "")
        path_only = _canonical_http_path(scope)
        
        # Extract headers for filtering decision
        headers = dict(scope.get("headers", []))
        headers_dict = {k.decode("utf-8") if isinstance(k, bytes) else k: 
                       v.decode("utf-8") if isinstance(v, bytes) else v 
                       for k, v in headers.items()}
        
        # Routine request tracing — DEBUG level, not WARNING.
        logger.debug(f"[OTEL-ALL-REQUESTS] {method} {path_only}")

        if any(pattern in path_only.lower() for pattern in ["/config", "/tables", "/few-shot"]):
            x_internal = headers_dict.get("x-internal") or headers_dict.get("X-Internal") or "none"
            logger.debug(f"[OTEL-TRACE-DEBUG] Endpoint hit: {method} {path_only} | X-Internal: {x_internal}")
        
        # Check if this path should be traced
        if not self._should_trace_path(path_only, headers_dict):
            await self.app(scope, receive, send)
            return
        
        tracer, service_name = self._resolve(path_only)

        if tracer is None:
            await self.app(scope, receive, send)
            return

        # Determine service prefix for later use
        service_prefix = None
        for prefix in SERVICE_ROUTE_MAP.keys():
            if path_only.startswith(prefix):
                service_prefix = prefix
                break

        # Start with raw path, will update after routing
        span_name = f"{method} {path_only}"
        logger.debug(f"[OTEL-SPAN-CREATE] Creating span: {span_name} | service: {service_name}")

        # If OTEL is broken (network/config), serve the request without tracing.
        # Tracing must never take down the agent.
        try:
            span_cm = tracer.start_as_current_span(span_name, kind=trace.SpanKind.SERVER)
        except Exception as e:
            logger.warning("[OTEL] failed to start request span (%s) — running untraced: %s", span_name, e)
            await self.app(scope, receive, send)
            return

        token = _current_tracer.set(tracer)
        try:
            with span_cm as span:
                span.set_attribute("http.method", method)
                span.set_attribute("service.component", service_name)

                async def send_wrapper(message):
                    if message["type"] == "http.response.start":
                        status_code = message.get("status", 0)
                        span.set_attribute("http.status_code", status_code)
                        if status_code >= 400:
                            span.set_status(
                                Status(StatusCode.ERROR, f"HTTP {status_code}")
                            )
                    await send(message)

                try:
                    await self.app(scope, receive, send_wrapper)

                    # Get route from FastAPI's router
                    route = scope.get("route")
                    if route is not None:
                        # FastAPI route found - use its path template with service prefix
                        route_path = getattr(route, "path", None)
                        if route_path and service_prefix:
                            # Combine service prefix + FastAPI route path
                            # e.g., /nl2sql/api + /v1/agents/{agent_id}/config
                            final_route = service_prefix + route_path
                            span.update_name(f"{method} {final_route}")
                            span.set_attribute("http.route", final_route)
                            span.set_attribute("url.path", final_route)
                            span.set_attribute("http.target", final_route)
                            logger.debug(f"[OTEL-SPAN-FINAL] Span completed: {method} {final_route} | http_route={final_route}")
                        else:
                            # No path in route or no service prefix, use normalized path
                            final_route = _normalize_path(path_only)
                            span.update_name(f"{method} {final_route}")
                            span.set_attribute("http.route", final_route)
                            span.set_attribute("url.path", final_route)
                            span.set_attribute("http.target", final_route)
                            logger.debug(f"[OTEL-SPAN-FINAL] Span completed: {method} {final_route} | http_route={final_route}")
                    else:
                        # No route found - use normalized path
                        final_route = _normalize_path(path_only)
                        span.update_name(f"{method} {final_route}")
                        span.set_attribute("http.route", final_route)
                        span.set_attribute("url.path", final_route)
                        span.set_attribute("http.target", final_route)
                        logger.debug(f"[OTEL-SPAN-FINAL] Span completed: {method} {final_route} | http_route={final_route}")

                except Exception as exc:
                    span.record_exception(exc)
                    span.set_status(Status(StatusCode.ERROR, str(exc)))
                    raise
        finally:
            _current_tracer.reset(token)


def _get_active_tracer():
    """Returns the request-scoped tracer set by SmartTracingMiddleware."""
    return _current_tracer.get()


def _safe_start_span(tracer, span_name):
    """Try to open an OTEL span. Returns a context manager if successful,
    or None if tracing is broken — in which case the caller should run
    the wrapped function with no tracing wrapper.

    OTEL failures must NEVER take down the agent. The trace is best-effort.
    """
    if tracer is None:
        return None
    try:
        return tracer.start_as_current_span(span_name)
    except Exception as e:
        logger.warning("[OTEL] start_span failed for %s: %s — running without trace", span_name, e)
        return None


def track_time(func_or_name=None):
    def _wrap(func, span_name):

        if inspect.isasyncgenfunction(func):
            @functools.wraps(func)
            async def wrapper(*args, **kwargs):
                cm = _safe_start_span(_get_active_tracer(), span_name)
                if cm is None:
                    async for item in func(*args, **kwargs):
                        yield item
                    return
                try:
                    with cm:
                        async for item in func(*args, **kwargs):
                            yield item
                except Exception:
                    # Span context manager exit may swallow / re-raise — let it propagate
                    raise
            return wrapper

        elif inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def wrapper(*args, **kwargs):
                cm = _safe_start_span(_get_active_tracer(), span_name)
                if cm is None:
                    return await func(*args, **kwargs)
                try:
                    with cm:
                        return await func(*args, **kwargs)
                except Exception:
                    raise
            return wrapper

        else:
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                cm = _safe_start_span(_get_active_tracer(), span_name)
                if cm is None:
                    return func(*args, **kwargs)
                try:
                    with cm:
                        return func(*args, **kwargs)
                except Exception:
                    raise
            return wrapper

    if callable(func_or_name):
        return _wrap(func_or_name, func_or_name.__qualname__)
    else:
        def decorator(func):
            return _wrap(func, func_or_name or func.__qualname__)
        return decorator