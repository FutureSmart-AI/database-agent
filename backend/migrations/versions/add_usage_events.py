"""Usage events store owned by NL2SQL

Revision ID: add_usage_events
Revises: add_nl2sql_owner_config
Create Date: 2026-08-19 00:00:00.000000

Two new tables, `usage_events` and `usage_metrics` — NL2SQL's own copy of the usage
tracking store, ported from fs-agent-usage-limits.

WHY, given `nl2sql_agent_health_events` already exists: they answer different questions.
Agent Health is one row per CHAT QUERY, agent-scoped, and only as old as the feature
(52 rows from 2026-08-13). Usage events are one row per OPERATION — each LLM call, SQL
execution, chart generation — OWNER-scoped, with full history. The Usage & Limits screen
is owner-level over months, which the health table cannot serve.

Two deliberate differences from the source schema:
  * `usage_events.owner_id` has NO foreign key. Upstream it references
    `owner_configurations.owner_id`; here an owner is the email on
    `chatbot_details.owner_id`, so it is a plain indexed string.
  * `usage_metrics.event_id` KEEPS `ON DELETE CASCADE` — a metric is meaningless without
    its event.

The attribution columns use PARTIAL indexes: most rows populate only one or two of
owner_id / agent_id / service_id / session_id / request_id / key_type, so indexing the
NULLs would be dead weight on a path written to on every LLM call.

`metadata` gets a GIN index because the analytics reads filter inside it
(`metadata @> '{"provider": "anthropic"}'`).

Revision IDs stay under 32 characters — `alembic_version.version_num` is `varchar(32)`,
and a longer id fails the upgrade *after* the DDL has run.

Idempotent: tables and indexes are created only if absent.

NOTE: migrations are applied MANUALLY in this repo (the deploy job does not run them).
Apply before deploying the code that writes these tables, or events are dropped until it
runs — the writer swallows its own errors by design, so nothing will alert you.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'add_usage_events'
down_revision = 'add_nl2sql_owner_config'
branch_labels = None
depends_on = None

EVENTS = 'usage_events'
METRICS = 'usage_metrics'

# (index, table, columns, partial-where or None, using or None)
INDEXES = [
    ('idx_events_owner_time',    EVENTS,  ['owner_id', 'timestamp'],                  'owner_id IS NOT NULL',   None),
    ('idx_events_key_type_time', EVENTS,  ['key_type', 'timestamp'],                  'key_type IS NOT NULL',   None),
    ('idx_events_agent_time',    EVENTS,  ['agent_id', 'timestamp'],                  'agent_id IS NOT NULL',   None),
    ('idx_events_service_op',    EVENTS,  ['service_type', 'operation', 'timestamp'], None,                     None),
    ('idx_events_session',       EVENTS,  ['session_id', 'timestamp'],                'session_id IS NOT NULL', None),
    ('idx_events_request',       EVENTS,  ['request_id', 'timestamp'],                'request_id IS NOT NULL', None),
    ('idx_events_service_id',    EVENTS,  ['service_id', 'timestamp'],                'service_id IS NOT NULL', None),
    ('idx_events_timestamp',     EVENTS,  ['timestamp'],                              None,                     None),
    ('idx_events_metadata_gin',  EVENTS,  ['metadata'],                               None,                     'gin'),
    ('idx_metrics_event',        METRICS, ['event_id'],                               None,                     None),
    ('idx_metrics_name',         METRICS, ['metric_name'],                            None,                     None),
    ('idx_metrics_name_value',   METRICS, ['metric_name', 'metric_value'],            None,                     None),
]


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(name):
    return name in _inspector().get_table_names()


def _existing_indexes(table):
    return {i['name'] for i in _inspector().get_indexes(table)}


def upgrade():
    if not _has_table(EVENTS):
        op.create_table(
            EVENTS,
            sa.Column('event_id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            # No FK — NL2SQL has no owner registry; see the module docstring.
            sa.Column('owner_id', sa.String(255), nullable=True),
            # 'platform-key' | 'owner-key' — whose key paid for the call.
            sa.Column('key_type', sa.String(50), nullable=True),
            sa.Column('agent_id', sa.String(255), nullable=True),
            sa.Column('service_id', sa.String(255), nullable=True),
            sa.Column('service_type', sa.String(100), nullable=False),
            sa.Column('operation', sa.String(100), nullable=False),
            sa.Column('label', sa.String(100), nullable=True),
            sa.Column('session_id', sa.String(255), nullable=True),
            sa.Column('request_id', sa.String(255), nullable=True),
            sa.Column('operation_id', sa.String(255), nullable=True),
            # When the operation happened, as reported by the caller.
            sa.Column('timestamp', sa.TIMESTAMP(timezone=True), nullable=False),
            sa.Column('metadata', postgresql.JSONB(), nullable=True),
            sa.Column('created_at', sa.TIMESTAMP(timezone=True),
                      server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        )

    if not _has_table(METRICS):
        op.create_table(
            METRICS,
            sa.Column('metric_id', sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column('event_id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('metric_name', sa.String(100), nullable=False),
            # NUMERIC(20,4): token counts and second-precision durations in one column,
            # summable without float drift.
            sa.Column('metric_value', sa.Numeric(20, 4), nullable=False),
            sa.Column('created_at', sa.TIMESTAMP(timezone=True),
                      server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
            sa.ForeignKeyConstraint(['event_id'], [f'{EVENTS}.event_id'],
                                    name='usage_metrics_event_id_fkey', ondelete='CASCADE'),
        )

    for name, table, cols, where, using in INDEXES:
        if name in _existing_indexes(table):
            continue
        kw = {}
        if where:
            kw['postgresql_where'] = sa.text(where)
        if using:
            kw['postgresql_using'] = using
        op.create_index(name, table, cols, **kw)


def downgrade():
    # Metrics first — the FK points at usage_events.
    if _has_table(METRICS):
        op.drop_table(METRICS)
    if _has_table(EVENTS):
        op.drop_table(EVENTS)
