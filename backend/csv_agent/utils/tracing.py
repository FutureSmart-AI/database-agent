import os
from typing import Optional, Dict, Any

from dotenv import load_dotenv

# Optional: Only import when available to avoid ImportError at import time
try:
    from langsmith import Client
    from langsmith.run_helpers import traceable, get_current_run_tree, get_current_run, trace as _trace
except Exception:  # pragma: no cover
    Client = None
    def traceable(fn=None, *args, **kwargs):  # type: ignore
        # no-op decorator if langsmith not available
        if fn is None:
            def wrapper(f):
                return f
            return wrapper
        return fn
    def get_current_run_tree():
        return None
    def get_current_run():
        return None
    # simple no-op context manager
    from contextlib import contextmanager
    @contextmanager
    def _trace(*args, **kwargs):  # type: ignore
        yield

# load_dotenv()  # Rely on main.py or central config loader

_LANGSMITH_INITIALIZED = False


def init_tracing(project_name: Optional[str] = None, tags: Optional[list[str]] = None) -> None:
    """
    Initialize LangSmith tracing if environment variables are set.

    Required env vars: LANGSMITH_API_KEY
    Optional env vars: LANGSMITH_ENDPOINT, LANGSMITH_PROJECT (or LANGCHAIN_PROJECT)
    """
    global _LANGSMITH_INITIALIZED
    if _LANGSMITH_INITIALIZED:
        return

    api_key = os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY")
    if not api_key or Client is None:
        return  # gracefully skip if not configured

    endpoint = os.getenv("LANGSMITH_ENDPOINT") or os.getenv("LANGCHAIN_ENDPOINT")
    project = project_name or os.getenv("LANGSMITH_PROJECT") or os.getenv("LANGCHAIN_PROJECT")

    # Touch client to verify config; errors should not crash the app
    try:
        _ = Client(api_url=endpoint, api_key=api_key)
        _LANGSMITH_INITIALIZED = True
    except Exception:
        # Swallow errors to avoid failing the service
        _LANGSMITH_INITIALIZED = False


def get_trace_context() -> Dict[str, Any]:
    """Return current LangSmith run metadata if available."""
    try:
        run = get_current_run()
        if not run:
            return {}
        return {
            "run_id": getattr(run, "id", None),
            "name": getattr(run, "name", None),
            "parent_id": getattr(run, "parent_run_id", None),
        }
    except Exception:
        return {}


# Re-export a safe trace context manager
trace = _trace

__all__ = [
    "init_tracing",
    "traceable",
    "get_trace_context",
    "trace",
] 