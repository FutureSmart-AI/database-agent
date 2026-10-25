"""
RESTful API routers for NL2SQL agents.

This package contains all the RESTful API endpoints organized by resource type.
"""

from .agents import router as agents_router
from .api_keys import router as api_keys_router
from .config import router as config_router
from .databases import router as databases_router
from .databases_fewshot import router as databases_fewshot_router
from .databases_tables import router as databases_tables_router
from .databases_hc import router as databases_hc_router
from .chat import router as chat_router
from .feedback import router as feedback_router
from .statistics import router as statistics_router
from .analytics import router as analytics_router
from .credentials import router as credentials_router
from .owner_config import router as owner_config_router
from .usage_events import router as usage_events_router
from .invitations import router as invitations_router
from .utility import router as utility_router
from .sessions import router as sessions_router
from .service import router as service_router
from .widgets import router as widgets_router

__all__ = [
    "agents_router",
    "api_keys_router",
    "config_router",
    "databases_router",
    "databases_fewshot_router",
    "databases_tables_router",
    "databases_hc_router",
    "chat_router",
    "feedback_router",
    "statistics_router",
    "analytics_router",
    "credentials_router",
    "owner_config_router",
    "usage_events_router",
    "invitations_router",
    "utility_router",
    "service_router",
    "sessions_router",
    "widgets_router",
]

