"""Batch Query Reports tables

Revision ID: add_batch_query_reports
Revises: merge_voice_drop_api_key_scope
Create Date: 2026-08-12 00:00:00.000000

Six new tables, all owned by NL2SQL:

- `report_settings`     per-agent settings; currently the per-report query cap
- `reports`             the report definition/template (query groups, prompt, schedule)
- `report_runs`         one execution of a report
- `report_run_groups`   a run's pre-materialized groups (stable group_id)
- `report_run_queries`  a run's pre-materialized queries (stable query_id)
- `report_run_results`  per-query output, keyed uniquely on (run_id, query_id)

The unique constraint on `report_run_results (run_id, query_id)` is load-bearing, not
decorative: it is the upsert key that makes a retried result write idempotent.

`reports.query_groups`, `reports.schedule` and `report_run_results.execution_details` are JSONB
— the first two because the group/query structure is a document the API round-trips whole, the
third because its shape is owned by the chat endpoint (executed SQL, result table, chart data)
and will grow with it.

NOTE the Agent Dashboard has tables of the same names in ITS database. The two services keep
separate reports; nothing is shared.

Revision IDs are kept under 32 characters — `alembic_version.version_num` is `varchar(32)`, and
a longer id fails the upgrade *after* the DDL has run (see add_widget_and_public_access).

Idempotent: every table and index is created only if absent, so re-running is safe.

NOTE: migrations are applied MANUALLY in this repo (the deploy job does not run them). Run this
by hand against dev and prod BEFORE deploying the code that reads these tables — the reports
routers `select` from them, and PostgreSQL raises UndefinedTable on an unmigrated database.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'add_batch_query_reports'
down_revision = 'merge_voice_drop_api_key_scope'
branch_labels = None
depends_on = None

SETTINGS_TABLE = 'report_settings'
REPORTS_TABLE = 'reports'
RUNS_TABLE = 'report_runs'
GROUPS_TABLE = 'report_run_groups'
QUERIES_TABLE = 'report_run_queries'
RESULTS_TABLE = 'report_run_results'

# (index name, table, columns) — created after the tables, only when missing.
INDEXES = [
    ('ix_reports_agent_id', REPORTS_TABLE, ['agent_id']),
    ('ix_reports_user_id', REPORTS_TABLE, ['user_id']),
    ('ix_reports_next_run_at', REPORTS_TABLE, ['next_run_at']),
    ('idx_reports_agent_deleted', REPORTS_TABLE, ['agent_id', 'deleted']),
    ('ix_report_runs_report_id', RUNS_TABLE, ['report_id']),
    ('ix_report_runs_agent_id', RUNS_TABLE, ['agent_id']),
    ('ix_report_runs_user_id', RUNS_TABLE, ['user_id']),
    ('idx_report_runs_report', RUNS_TABLE, ['report_id']),
    ('idx_report_runs_agent', RUNS_TABLE, ['agent_id']),
    ('ix_report_run_groups_run_id', GROUPS_TABLE, ['run_id']),
    ('idx_run_groups_run', GROUPS_TABLE, ['run_id']),
    ('ix_report_run_queries_run_id', QUERIES_TABLE, ['run_id']),
    ('ix_report_run_queries_group_id', QUERIES_TABLE, ['group_id']),
    ('idx_run_queries_run', QUERIES_TABLE, ['run_id']),
    ('idx_run_queries_group', QUERIES_TABLE, ['group_id']),
    ('ix_report_run_results_run_id', RESULTS_TABLE, ['run_id']),
    ('ix_report_run_results_query_id', RESULTS_TABLE, ['query_id']),
    ('idx_run_results_run', RESULTS_TABLE, ['run_id']),
]


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(name):
    return name in _inspector().get_table_names()


def _existing_indexes(table):
    return {i['name'] for i in _inspector().get_indexes(table)}


def upgrade():
    if not _has_table(SETTINGS_TABLE):
        op.create_table(
            SETTINGS_TABLE,
            sa.Column('agent_id', sa.String(), primary_key=True),
            sa.Column('max_queries_per_report', sa.Integer(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.Column('updated_by', sa.String(), nullable=True),
        )

    if not _has_table(REPORTS_TABLE):
        op.create_table(
            REPORTS_TABLE,
            sa.Column('report_id', sa.String(), primary_key=True),
            sa.Column('agent_id', sa.String(), nullable=False),
            sa.Column('user_id', sa.String(), nullable=False),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('report_instructions', sa.String(), nullable=True),
            sa.Column('query_groups', postgresql.JSONB(), nullable=True),
            sa.Column('analysis_prompt', sa.String(), nullable=True),
            sa.Column('schedule', postgresql.JSONB(), nullable=True),
            sa.Column('next_run_at', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.Column('deleted', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('updated_by', sa.String(), nullable=True),
            sa.Column('deleted_by', sa.String(), nullable=True),
            sa.Column('deleted_at', sa.DateTime(), nullable=True),
        )

    if not _has_table(RUNS_TABLE):
        op.create_table(
            RUNS_TABLE,
            sa.Column('run_id', sa.String(), primary_key=True),
            sa.Column('report_id', sa.String(), nullable=False),
            sa.Column('agent_id', sa.String(), nullable=False),
            sa.Column('user_id', sa.String(), nullable=False),
            sa.Column('status', sa.String(), nullable=False, server_default='pending'),
            sa.Column('trigger', sa.String(), nullable=False, server_default='manual'),
            sa.Column('started_at', sa.DateTime(), nullable=True),
            sa.Column('ended_at', sa.DateTime(), nullable=True),
            sa.Column('failure_reason', sa.String(), nullable=True),
            sa.Column('overall_summary', sa.String(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.Column('updated_by', sa.String(), nullable=True),
        )

    if not _has_table(GROUPS_TABLE):
        op.create_table(
            GROUPS_TABLE,
            sa.Column('group_id', sa.String(), primary_key=True),
            sa.Column('run_id', sa.String(), nullable=False),
            sa.Column('type', sa.String(), nullable=False),
            sa.Column('position', sa.Integer(), nullable=False),
        )

    if not _has_table(QUERIES_TABLE):
        op.create_table(
            QUERIES_TABLE,
            sa.Column('query_id', sa.String(), primary_key=True),
            sa.Column('run_id', sa.String(), nullable=False),
            sa.Column('group_id', sa.String(), nullable=False),
            sa.Column('position', sa.Integer(), nullable=False),
            sa.Column('text', sa.String(), nullable=False),
        )

    if not _has_table(RESULTS_TABLE):
        op.create_table(
            RESULTS_TABLE,
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('run_id', sa.String(), nullable=False),
            sa.Column('group_id', sa.String(), nullable=False),
            sa.Column('query_id', sa.String(), nullable=False),
            sa.Column('session_id', sa.String(), nullable=True),
            sa.Column('chat_id', sa.String(), nullable=True),
            sa.Column('answer', sa.String(), nullable=True),
            sa.Column('execution_details', postgresql.JSONB(), nullable=True),
            sa.Column('response_time_ms', sa.Integer(), nullable=True),
            sa.Column('token_usage', sa.Integer(), nullable=True),
            sa.Column('is_answered', sa.Boolean(), nullable=True),
            sa.Column('error', sa.String(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            # The upsert key: one result row per query of a run, so a retry updates instead of
            # duplicating.
            sa.UniqueConstraint('run_id', 'query_id', name='uq_run_results_run_query'),
        )

    for index_name, table, columns in INDEXES:
        if index_name not in _existing_indexes(table):
            op.create_index(index_name, table, columns)


def downgrade():
    # Children before parents, so nothing is orphaned mid-downgrade.
    for table in (RESULTS_TABLE, QUERIES_TABLE, GROUPS_TABLE, RUNS_TABLE, REPORTS_TABLE, SETTINGS_TABLE):
        if _has_table(table):
            op.drop_table(table)
