"""Request/response models for usage events.

Ported from fs-agent-usage-limits (`services/pydantic_models_usage_events.py`) now that
NL2SQL records its own usage instead of POSTing it to that service.

Covers both directions: the WRITE path used in-process by `agent.utils.usage_tracking`,
and the READ path served by `api/v1/routers/usage_events.py` for the owner-level Usage
screens.

Upgraded to Pydantic v2 to match this repo, and `owner_id` is a plain `str` rather than
`EmailStr` because NL2SQL types owner emails that way and does not depend on
`email-validator`.
"""
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing import Optional, Dict, List, Any, Literal
from datetime import datetime, timezone, timedelta
from enum import Enum


# ===== Service Type Enum =====
class ServiceType(str, Enum):
    """The service an event came from.

    Only `nl2sql` — this store holds THIS service's usage. Upstream the enum also lists
    knowledge, actions, integrations, dashboard and orchestrator, because one shared table
    received all of them. Here every row is NL2SQL's own, so advertising the others would
    invite a caller to write a row nothing in this service can account for.

    It carries a default, so callers need not send it and cannot get it wrong.
    """
    NL2SQL = "nl2sql"


# ===== Metric Model =====
class UsageMetric(BaseModel):
    """A single metric measurement."""
    name: str = Field(..., min_length=1, max_length=100)
    value: float

    @field_validator('value')
    @classmethod
    def validate_value(cls, v):
        if not isinstance(v, (int, float)):
            raise ValueError('metric value must be numeric')
        return v

    model_config = ConfigDict(json_schema_extra= {
        "example": {
            "name": "input_tokens",
            "value": 2500
        }
    }
    )
# ===== Event Request Model =====
class UsageEventRequest(BaseModel):
    """Single usage event to be recorded.

    At least one of owner_id, agent_id, or service_id must be provided for proper attribution.
    For cost tracking, specify key_type as either 'platform-key' or 'owner-key'.
    """
    # Plain str, not EmailStr: this repo types owner emails as str everywhere
    # (see api/v1/schemas/agents.py) and does not depend on `email-validator`.
    owner_id: Optional[str] = None
    key_type: Optional[Literal["platform-key", "owner-key"]] = Field(None, description="Type of key for cost tracking: 'platform-key' or 'owner-key'")
    agent_id: Optional[str] = Field(None, min_length=1, max_length=255)
    service_id: Optional[str] = Field(None, min_length=1, max_length=255)
    service_type: ServiceType = ServiceType.NL2SQL
    operation: str = Field(..., min_length=1, max_length=100)
    # ISO8601 WITH a timezone, not in the future, and no more than 7 days old (see
    # validate_timestamp). Older events are refused rather than backfilled: usage windows
    # are billed, and a late arrival would land in the wrong period.
    timestamp: str
    label: Optional[str] = Field(None, max_length=100)
    session_id: Optional[str] = Field(None, max_length=255)
    request_id: Optional[str] = Field(None, max_length=255)
    operation_id: Optional[str] = Field(None, max_length=255)
    metadata: Optional[Dict[str, Any]] = None
    metrics: Optional[List[UsageMetric]] = None

    @field_validator('timestamp')
    @classmethod
    def validate_timestamp(cls, v):
        """Validate ISO8601 format and reasonable time range."""
        try:
            # Parse ISO8601
            dt = datetime.fromisoformat(v.replace('Z', '+00:00'))

            # Ensure timezone-aware
            if dt.tzinfo is None:
                raise ValueError('timestamp must include timezone information (use ISO8601 format with Z or +00:00)')

            now = datetime.now(timezone.utc)

            # Not in future
            if dt > now:
                raise ValueError('timestamp cannot be in the future')

            # Not older than 7 days
            if (now - dt) > timedelta(days=7):
                raise ValueError('timestamp cannot be older than 7 days')

            return v
        except (ValueError, AttributeError) as e:
            if 'timestamp must include timezone' in str(e):
                raise
            raise ValueError(f'Invalid ISO8601 timestamp: {e}')

    @field_validator('metrics')
    @classmethod
    def validate_metrics(cls, v):
        """Validate metrics array."""
        if v is not None and len(v) > 100:
            raise ValueError('Maximum 100 metrics per event')
        return v

    @field_validator('metadata')
    @classmethod
    def validate_metadata_depth(cls, v):
        """Validate metadata JSON depth."""
        if v is None:
            return v

        def get_depth(obj, current_depth=1):
            if not isinstance(obj, dict):
                return current_depth
            if not obj:
                return current_depth
            return max(get_depth(val, current_depth + 1) for val in obj.values())

        depth = get_depth(v)
        if depth > 5:
            raise ValueError('metadata JSON depth cannot exceed 5 levels')
        return v

    @model_validator(mode='after')
    def validate_attribution_context(self):
        """Ensure at least one attribution field is provided.

        Without one of these an event cannot be billed or charted to anyone, so it is
        rejected at the edge rather than stored as unattributable noise.
        """
        if not any([self.owner_id, self.agent_id, self.service_id]):
            raise ValueError(
                'At least one of owner_id, agent_id, or service_id must be provided'
            )

        return self

    model_config = ConfigDict(json_schema_extra= {
        "examples": [
            {
                "summary": "LLM call from the sql_gen node",
                "value": {
                    "owner_id": "customer@example.com",
                    "agent_id": "NL2SQL_39F3787E",
                    "operation": "llm_call",
                    "label": "sql_gen_llm",
                    "key_type": "platform-key",
                    "session_id": "sess_789",
                    "request_id": "req_abc",
                    "timestamp": "2026-08-19T10:30:00Z",
                    "metadata": {
                        "provider": "google",
                        "model_name": "gemini-3.5-flash-lite"
                    },
                    "metrics": [
                        {"name": "input_tokens", "value": 2500},
                        {"name": "output_tokens", "value": 350},
                        {"name": "total_tokens", "value": 2850},
                        {"name": "execution_time_seconds", "value": 1.24}
                    ]
                }
            },
            {
                "summary": "SQL run on the customer database (no tokens)",
                "value": {
                    "owner_id": "customer@example.com",
                    "agent_id": "NL2SQL_39F3787E",
                    "operation": "sql_execution",
                    "key_type": "owner-key",
                    "timestamp": "2026-08-19T10:31:00Z",
                    "metrics": [
                        {"name": "response_time_ms", "value": 45}
                    ]
                }
            }
        ]
    }
    )
# ===== Bulk Request Model =====
class UsageEventsRequest(BaseModel):
    """Bulk usage event recording request."""
    events: List[UsageEventRequest]

    @field_validator('events')
    @classmethod
    def validate_events(cls, v):
        if not v:
            raise ValueError('events array cannot be empty')
        if len(v) > 1000:
            raise ValueError('maximum 1000 events per request')
        return v

    model_config = ConfigDict(json_schema_extra= {
        "example": {
            "events": [
                {
                    "owner_id": "customer@example.com",
                    "agent_id": "NL2SQL_39F3787E",
                    "operation": "llm_call",
                    "timestamp": "2026-08-19T10:30:00Z",
                    "metrics": [
                        {"name": "input_tokens", "value": 900},
                        {"name": "output_tokens", "value": 120}
                    ]
                },
                {
                    "owner_id": "customer@example.com",
                    "agent_id": "NL2SQL_39F3787E",
                    "operation": "chart_generation",
                    "timestamp": "2026-08-19T10:31:00Z",
                    "metrics": [{"name": "total_tokens", "value": 640}]
                }
            ]
        }
    }
    )
# ===== Response Models =====
class FailedEvent(BaseModel):
    """Details of a failed event."""
    index: int
    error: str
    event: Dict[str, Any]


class UsageEventsResponse(BaseModel):
    """Response from bulk event recording."""
    processed_count: int
    failed_count: int
    failed_events: List[FailedEvent] = Field(default_factory=list)

    model_config = ConfigDict(json_schema_extra= {
        "example": {
            "processed_count": 5,
            "failed_count": 0,
            "failed_events": []
        }
    }
    )
# ===== Retrieval Response Models =====

class EventMetricResponse(BaseModel):
    """Metric data in event response."""
    name: str
    value: float


class UsageEventResponse(BaseModel):
    """Single usage event in retrieval response."""
    event_id: str
    owner_id: Optional[str] = None
    key_type: Optional[str] = None
    agent_id: Optional[str] = None
    # No `service_id`. The column exists and is written (the central usage service resolves
    # agents through it), but NL2SQL sets it to the same value as agent_id — returning both
    # would show one id twice and invite callers to filter on the wrong one.
    service_type: str
    operation: str
    timestamp: str
    label: Optional[str] = None
    session_id: Optional[str] = None
    request_id: Optional[str] = None
    operation_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    metrics: List[EventMetricResponse] = Field(default_factory=list)
    created_at: str

    model_config = ConfigDict(json_schema_extra= {
        "example": {
            "event_id": "550e8400-e29b-41d4-a716-446655440000",
            "owner_id": "customer@example.com",
            "agent_id": "NL2SQL_39F3787E",
            "service_type": "nl2sql",
            "operation": "llm_call",
            "timestamp": "2026-08-19T10:30:00Z",
            "label": "sql_gen_llm",
            "session_id": "sess_789",
            "request_id": "req_abc",
            "operation_id": "op_xyz",
            "metadata": {"provider": "google", "model_name": "gemini-3.5-flash-lite"},
            "metrics": [
                {"name": "input_tokens", "value": 2500},
                {"name": "output_tokens", "value": 350}
            ],
            "created_at": "2026-08-19T10:30:01Z"
        }
    }
    )
class UsageEventsListResponse(BaseModel):
    """Paginated list of usage events."""
    total_count: int
    events: List[UsageEventResponse]
    limit: int
    offset: int

    model_config = ConfigDict(json_schema_extra= {
        "example": {
            "total_count": 150,
            "events": [],
            "limit": 50,
            "offset": 0
        }
    }
    )
class AggregatedMetric(BaseModel):
    """Aggregated metric data."""
    metric_name: str
    total: float
    avg: float
    min: float
    max: float
    count: int

    model_config = ConfigDict(json_schema_extra= {
        "example": {
            "metric_name": "input_tokens",
            "total": 125000,
            "avg": 2500,
            "min": 100,
            "max": 8000,
            "count": 50
        }
    }
    )
class AggregatedUsageResponse(BaseModel):
    """Aggregated usage data grouped by specified dimensions."""
    group_by: List[str]
    groups: List[Dict[str, Any]]

    model_config = ConfigDict(json_schema_extra= {
        "example": {
            "group_by": ["operation"],
            "groups": [
                {
                    "operation": "llm_call",
                    "event_count": 50,
                    "metrics": [
                        {
                            "metric_name": "input_tokens",
                            "total": 125000,
                            "avg": 2500,
                            "min": 100,
                            "max": 8000,
                            "count": 50
                        }
                    ]
                }
            ]
        }
    }
    )
class ServiceOperationSummary(BaseModel):
    """Summary for a specific service and operation."""
    service_type: str
    operation: str
    event_count: int
    metrics: List[AggregatedMetric] = Field(default_factory=list)


class UsageSummaryResponse(BaseModel):
    """Usage summary for an owner."""
    owner_id: str
    start_date: str
    end_date: str
    total_events: int
    services: List[ServiceOperationSummary]

    model_config = ConfigDict(json_schema_extra= {
        "example": {
            "owner_id": "customer@example.com",
            "start_date": "2026-08-01T00:00:00Z",
            "end_date": "2026-08-19T23:59:59Z",
            "total_events": 250,
            "services": [
                {
                    "service_type": "nl2sql",
                    "operation": "llm_call",
                    "event_count": 150,
                    "metrics": [
                        {
                            "metric_name": "input_tokens",
                            "total": 375000,
                            "avg": 2500,
                            "min": 100,
                            "max": 8000,
                            "count": 150
                        }
                    ]
                }
            ]
        }
    }
    )