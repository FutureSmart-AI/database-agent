"""Request/response models for the Batch Query Reports API.

Public (user-facing) and internal (worker-facing) models live together; each router imports
what it needs. Response models are declared for the shapes Swagger benefits from — the full
run payload is deliberately left schema-free (`Dict[str, Any]`) because it embeds the chat
endpoint's own `execution_details`/`chart_output` shapes, which this feature does not own.
"""
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

GroupType = Literal["independent", "sequential"]
Frequency = Literal["daily", "weekly", "monthly", "cron"]
InternalStatus = Literal["running", "completed", "failed"]


# ---------------------------------------------------------------------------
# Public — report definition
# ---------------------------------------------------------------------------

class QueryGroupInput(BaseModel):
    type: GroupType = Field(
        ...,
        description=(
            "independent = the group's queries run in parallel, each in its own session. "
            "sequential = they run in order sharing one session, so each question sees the "
            "previous answers."
        ),
    )
    queries: List[str] = Field(..., description="Natural-language questions, in order")


class ScheduleInput(BaseModel):
    frequency: Frequency = Field(..., description="daily | weekly | monthly | cron")
    cron: Optional[str] = Field(None, description="5-field cron expression; required when frequency=cron")
    timezone: Optional[str] = Field("UTC", description="IANA timezone the cron expression is evaluated in")


class CreateReportRequest(BaseModel):
    name: str
    report_instructions: Optional[str] = Field(
        None, description="Report-level instructions applied to every query (e.g. 'answer concisely')"
    )
    query_groups: List[QueryGroupInput]
    analysis_prompt: Optional[str] = Field(
        None, description="When set, an LLM summary of the whole run is generated after every query finishes"
    )
    schedule: Optional[ScheduleInput] = None
    run_immediately: bool = Field(False, description="Also create and start a run right away")


class UpdateReportRequest(BaseModel):
    """Every field is optional; only what is sent is written.

    An explicit `null` CLEARS `report_instructions`, `analysis_prompt` and `schedule`
    (clearing the schedule stops the report from firing). `name` and `query_groups` cannot be
    cleared — a report needs both — so a null for those is ignored.
    """
    name: Optional[str] = None
    report_instructions: Optional[str] = None
    query_groups: Optional[List[QueryGroupInput]] = None
    analysis_prompt: Optional[str] = None
    schedule: Optional[ScheduleInput] = None


class UpdateReportSettingsRequest(BaseModel):
    max_queries_per_report: int = Field(
        ..., description="Per-report query cap for this agent (1..1000)"
    )


# ---------------------------------------------------------------------------
# Public — responses
# ---------------------------------------------------------------------------

class CreateReportResponse(BaseModel):
    report_id: str
    run_id: Optional[str] = Field(None, description="Present only when run_immediately was true")


class ReportResponse(BaseModel):
    report_id: str
    agent_id: str
    user_id: Optional[str] = None
    name: str
    report_instructions: Optional[str] = None
    query_groups: Optional[List[Dict[str, Any]]] = None
    analysis_prompt: Optional[str] = None
    schedule: Optional[Dict[str, Any]] = None
    next_run_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ReportListResponse(BaseModel):
    reports: List[ReportResponse]


class ReportSettingsResponse(BaseModel):
    max_queries_per_report: int = Field(..., description="Effective limit for this agent")
    default_max_queries_per_report: int = Field(..., description="System default, so the UI never hardcodes it")


class RunProgress(BaseModel):
    total_queries: int
    completed_queries: int
    failed_queries: int
    percent_complete: int


class RunStatusResponse(BaseModel):
    run_id: str
    report_id: str
    agent_id: str
    status: str = Field(..., description="pending | running | completed | failed | cancelled")
    progress: RunProgress
    started_at: Optional[str] = None
    ended_at: Optional[str] = None


class RunListItem(BaseModel):
    run_id: str
    report_id: str
    status: str
    trigger: str
    progress: RunProgress
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    total_time_ms: Optional[int] = None
    created_at: Optional[str] = None


class RunListResponse(BaseModel):
    runs: List[RunListItem]


class RunCreatedResponse(BaseModel):
    run_id: str
    status: str


class CancelRunResponse(BaseModel):
    run_id: str
    status: Optional[str] = None


class MessageResponse(BaseModel):
    message: str


# ---------------------------------------------------------------------------
# Internal — worker-facing
# ---------------------------------------------------------------------------

class StatusUpdateRequest(BaseModel):
    status: InternalStatus
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    failure_reason: Optional[str] = Field(
        None, description="Why the WHOLE job died; a single failed query uses the result's `error`"
    )


class ResultItem(BaseModel):
    query_id: str
    group_id: str
    session_id: Optional[str] = None
    chat_id: Optional[str] = None
    answer: Optional[str] = None
    # Kept schema-free: the producer owns this shape (executed SQL, tables, db_result,
    # export_url, chart data) and the report view renders it like the live chat does.
    execution_details: Optional[Dict[str, Any]] = None
    response_time_ms: Optional[int] = None
    token_usage: Optional[int] = None
    is_answered: Optional[bool] = None
    error: Optional[str] = Field(None, description="Populated → this query failed")


class ResultsSubmitRequest(BaseModel):
    results: List[ResultItem]


class AnalysisSubmitRequest(BaseModel):
    overall_summary: str
