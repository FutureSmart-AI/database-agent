"""SQLModel tables for Batch Query Reports.

NL2SQL owns these in its own PostgreSQL database, alongside `models.sql_models`. They are
declared here rather than in `models/sql_models.py` so the whole feature stays in one
package, and they are imported by `migrations/env.py` so Alembic sees them.

NOTE: the Agent Dashboard has tables of the same names in *its* database. The two services
keep SEPARATE reports — a report created here is not visible there, exactly like
`widgets_settings`.

Resource model:
- Report          — the reusable definition/template (query groups, analysis prompt, schedule).
- ReportRun       — one execution of a Report (status, timing, analysis output).
- ReportRunGroup  — a pre-materialized group of a run (stable group_id).
- ReportRunQuery  — a pre-materialized query of a run (stable query_id).
- ReportRunResult — per-query output, upserted on (run_id, query_id) so retries are safe.
"""
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Column, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, Index, SQLModel


class ReportSettings(SQLModel, table=True):
    """Per-agent report settings, keyed by agent_id.

    Currently only the per-report query cap. When `max_queries_per_report` is NULL (or the
    agent has no row at all) the effective limit falls back to the
    REPORTS_MAX_QUERIES_PER_REPORT env default.
    """
    __tablename__ = "report_settings"
    __table_args__ = ({"extend_existing": True},)
    agent_id: str = Field(primary_key=True)
    max_queries_per_report: Optional[int] = None
    updated_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    updated_by: Optional[str] = None  # acting user on the last change


class Report(SQLModel, table=True):
    __tablename__ = "reports"
    __table_args__ = (
        Index("idx_reports_agent_deleted", "agent_id", "deleted"),
        {"extend_existing": True},
    )
    report_id: str = Field(primary_key=True)  # rep_<32hex>
    agent_id: str = Field(index=True)
    user_id: str = Field(index=True)  # fixed owner, set once at creation
    name: str
    report_instructions: Optional[str] = None
    query_groups: Optional[Any] = Field(default=None, sa_column=Column(JSONB))
    analysis_prompt: Optional[str] = None
    schedule: Optional[Any] = Field(default=None, sa_column=Column(JSONB))
    # When the next scheduled run is due (naive UTC); NULL when the report has no schedule.
    # The scheduler tick fires reports whose next_run_at <= now, then advances this.
    next_run_at: Optional[datetime] = Field(default=None, index=True)
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    # NULL until the first real update — no default_factory, so creation leaves it unset.
    updated_at: Optional[datetime] = None
    # Soft delete, consistent with the rest of NL2SQL: every reader filters `deleted == False`.
    deleted: bool = Field(default=False)
    # Kept separate from user_id so an edit or delete never overwrites the owner.
    updated_by: Optional[str] = None
    deleted_by: Optional[str] = None
    deleted_at: Optional[datetime] = None


class ReportRun(SQLModel, table=True):
    __tablename__ = "report_runs"
    __table_args__ = (
        Index("idx_report_runs_report", "report_id"),
        Index("idx_report_runs_agent", "agent_id"),
        {"extend_existing": True},
    )
    run_id: str = Field(primary_key=True)  # run_<32hex>
    report_id: str = Field(index=True)
    agent_id: str = Field(index=True)
    user_id: str = Field(index=True)  # who triggered it ("system" for scheduled runs)
    status: str = Field(default="pending")  # pending|running|completed|failed|cancelled
    trigger: str = Field(default="manual")  # manual|scheduled
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    failure_reason: Optional[str] = None
    overall_summary: Optional[str] = None
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    updated_by: Optional[str] = None  # acting user on a UI-driven transition (e.g. cancel)


class ReportRunGroup(SQLModel, table=True):
    __tablename__ = "report_run_groups"
    __table_args__ = (
        Index("idx_run_groups_run", "run_id"),
        {"extend_existing": True},
    )
    group_id: str = Field(primary_key=True)
    run_id: str = Field(index=True)
    type: str  # independent|sequential
    position: int


class ReportRunQuery(SQLModel, table=True):
    __tablename__ = "report_run_queries"
    __table_args__ = (
        Index("idx_run_queries_run", "run_id"),
        Index("idx_run_queries_group", "group_id"),
        {"extend_existing": True},
    )
    query_id: str = Field(primary_key=True)
    run_id: str = Field(index=True)
    group_id: str = Field(index=True)
    position: int  # order within the group — drives sequential execution order
    text: str


class ReportRunResult(SQLModel, table=True):
    __tablename__ = "report_run_results"
    __table_args__ = (
        UniqueConstraint("run_id", "query_id", name="uq_run_results_run_query"),
        Index("idx_run_results_run", "run_id"),
        {"extend_existing": True},
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: str = Field(index=True)
    group_id: str
    query_id: str = Field(index=True)
    session_id: Optional[str] = None  # chat session used; shared across a sequential group
    chat_id: Optional[str] = None     # the turn in nl2sql_logs this answer came from
    answer: Optional[str] = None
    # The NL2SQL execution trace, same shape the chat endpoint returns in `debug_info` plus
    # `chart_output`: {sql_query, tables_used, db_result, export_url, chart_suggestion,
    # chart_data, selected_db_id, selected_db_name}. Stored schema-free so the report view can
    # reuse the chat renderer as it evolves.
    execution_details: Optional[Any] = Field(default=None, sa_column=Column(JSONB))
    response_time_ms: Optional[int] = None
    token_usage: Optional[int] = None
    is_answered: Optional[bool] = None  # the agent's own "did I answer this" flag
    error: Optional[str] = None  # populated → this query failed
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
