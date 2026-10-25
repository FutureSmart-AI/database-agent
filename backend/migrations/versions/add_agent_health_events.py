"""Agent Health analytics table

Revision ID: add_agent_health_events
Revises: add_batch_query_reports
Create Date: 2026-08-13 00:00:00.000000

One new table, `nl2sql_agent_health_events` — one row per chat query, written by the
chat flow and read by the Agent Health / Analytics APIs
(`api/v1/routers/analytics.py`). NL2SQL used to be a sub-service of the orchestrator,
which kept this data in ITS `agent_health_events`; now that NL2SQL runs standalone it
owns its own copy. Nothing is shared between the two tables.

`chat_id` is UNIQUE — it is the idempotency key, so a retried write for the same query
is rejected by the constraint instead of double-counting the query in every aggregate.

`cost_usd` is nullable on purpose: NULL means "not priced yet", which readers must keep
distinct from 0.0, or unpriced spend gets reported as free. `cost_complete` records that
per row so a window can flag its total as a lower bound.

Revision IDs are kept under 32 characters — `alembic_version.version_num` is `varchar(32)`,
and a longer id fails the upgrade *after* the DDL has run.

Idempotent: the table and every index are created only if absent, so re-running is safe.

NOTE: migrations are applied MANUALLY in this repo (the deploy job does not run them). Run
this by hand against dev and prod BEFORE deploying the code that reads the table — the
analytics router `select`s from it, and PostgreSQL raises UndefinedTable on an unmigrated
database.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'add_agent_health_events'
down_revision = 'add_batch_query_reports'
branch_labels = None
depends_on = None

TABLE = 'nl2sql_agent_health_events'

# (index name, columns) — every column the read APIs filter or group by.
INDEXES = [
    ('ix_health_events_agent_id', ['agent_id']),
    ('ix_health_events_owner_id', ['owner_id']),
    ('ix_health_events_user_id', ['user_id']),
    ('ix_health_events_session_id', ['session_id']),
    ('ix_health_events_request_id', ['request_id']),
    ('ix_health_events_event_ts', ['event_ts']),
    ('ix_health_events_status', ['status']),
    ('ix_health_events_is_answered', ['is_answered']),
    ('ix_health_events_failure_category', ['failure_category']),
    ('ix_health_events_failed_stage', ['failed_stage']),
    ('ix_health_events_route', ['route']),
    ('ix_health_events_db_id', ['db_id']),
    ('ix_health_events_model', ['model']),
    # Every read path filters agent + window together, so serve both from one index.
    ('idx_health_events_agent_ts', ['agent_id', 'event_ts']),
]


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(name):
    return name in _inspector().get_table_names()


def _existing_indexes(table):
    return {i['name'] for i in _inspector().get_indexes(table)}


def upgrade():
    if not _has_table(TABLE):
        op.create_table(
            TABLE,
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('event_type', sa.String(), nullable=True, server_default='agent_query'),
            sa.Column('schema_version', sa.Integer(), nullable=True, server_default='1'),
            sa.Column('event_ts', sa.DateTime(), nullable=True),

            # identity
            sa.Column('agent_id', sa.String(), nullable=True),
            sa.Column('owner_id', sa.String(), nullable=True),
            sa.Column('user_id', sa.String(), nullable=True),
            sa.Column('session_id', sa.String(), nullable=True),
            sa.Column('chat_id', sa.String(), nullable=False),
            sa.Column('request_id', sa.String(), nullable=True),
            sa.Column('trace_id', sa.String(), nullable=True),
            sa.Column('langsmith_run_id', sa.String(), nullable=True),

            # what was asked
            sa.Column('query', sa.Text(), nullable=True),
            sa.Column('refined_query', sa.Text(), nullable=True),

            # how it was answered
            sa.Column('route', sa.String(), nullable=True),
            sa.Column('nodes_used', postgresql.JSONB(), nullable=True),
            sa.Column('db_id', sa.String(), nullable=True),
            sa.Column('db_ids', postgresql.JSONB(), nullable=True),
            sa.Column('cross_db', sa.Boolean(), nullable=True, server_default=sa.false()),
            sa.Column('sql_query', sa.Text(), nullable=True),
            sa.Column('selected_tables', postgresql.JSONB(), nullable=True),
            sa.Column('rows_returned', sa.Integer(), nullable=True),
            sa.Column('chart_generated', sa.Boolean(), nullable=True, server_default=sa.false()),
            sa.Column('pandas_used', sa.Boolean(), nullable=True, server_default=sa.false()),

            # outcome
            sa.Column('status', sa.String(), nullable=True),
            sa.Column('is_answered', sa.Boolean(), nullable=True, server_default=sa.false()),
            sa.Column('failure_category', sa.String(), nullable=True),
            sa.Column('failed_stage', sa.String(), nullable=True),
            sa.Column('failure_detail', sa.Text(), nullable=True),
            sa.Column('from_widget', sa.Boolean(), nullable=True, server_default=sa.false()),
            sa.Column('key_type', sa.String(), nullable=True),

            # metrics
            sa.Column('latency_ms', sa.Integer(), nullable=True, server_default='0'),
            sa.Column('db_fetch_ms', sa.Integer(), nullable=True, server_default='0'),
            sa.Column('sql_exec_ms', sa.Integer(), nullable=True, server_default='0'),
            sa.Column('input_tokens', sa.Integer(), nullable=True, server_default='0'),
            sa.Column('output_tokens', sa.Integer(), nullable=True, server_default='0'),
            sa.Column('total_tokens', sa.Integer(), nullable=True, server_default='0'),
            # Nullable: NULL = unpriced, which is NOT the same as 0.0.
            sa.Column('cost_usd', sa.Float(), nullable=True),
            sa.Column('cost_complete', sa.Boolean(), nullable=True, server_default=sa.false()),
            sa.Column('retry_count', sa.Integer(), nullable=True, server_default='0'),
            sa.Column('provider', sa.String(), nullable=True),
            sa.Column('model', sa.String(), nullable=True),
            sa.Column('node_data', postgresql.JSONB(), nullable=True),

            sa.Column('created_at', sa.DateTime(), nullable=True),
            # The idempotency key: one health row per query, so a retried write conflicts
            # instead of inflating the counts.
            sa.UniqueConstraint('chat_id', name='uq_health_events_chat_id'),
        )

    existing = _existing_indexes(TABLE)
    for index_name, columns in INDEXES:
        if index_name not in existing:
            op.create_index(index_name, TABLE, columns)


def downgrade():
    if _has_table(TABLE):
        op.drop_table(TABLE)
