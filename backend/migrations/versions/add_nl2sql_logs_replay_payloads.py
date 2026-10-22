"""nl2sql_logs: store the built answer payload so a reopened conversation replays it

Revision ID: add_nl2sql_logs_replay_payloads
Revises: query_cap_daily
Create Date: 2026-08-25 00:00:00.000000

A conversation reopened from the sessions API lost its chart, its data table and the tables the
answer came from. The transcript row kept only scalar columns (sql_query, db_output, graph_output),
so the replay path had to re-derive a response shape from them — and could not:

  selected_tables   no column at all, so "sources" had nowhere to come from
  db_output         bare rows (`[["partial_day", 53], …]`) with the column names dropped
  selected_db_*     the database the multi-DB router picked was not recorded
  export_url        the S3 link for a truncated result set was not recorded

fs-agent-chat solved the same problem by storing the *built* payload as JSON and handing that same
object back on replay, instead of rebuilding a second shape from scalars. These two columns give
nl2sql_logs the same thing:

  debug_info    the debug block build_chat_response produced for this turn — query, refined_query,
                selected_db_id/name, sql_query, selected_tables, the tabular db_result block and
                export_url
  chart_output  the chart block in the response's own key names (chart_suggestion / chart_data /
                metadata)

The existing scalar columns keep being written: analytics, feedback and the "last SQL for this
session" lookup read them, and `graph_output` stays the legacy chart record. Rows written before
this migration have NULL here, so the read path falls back to the scalars for them.

Idempotent: each column is added only if absent, so this is safe to re-run.

NOTE: migrations are applied MANUALLY in this repo (the deploy job does not run them), so this
must be run by hand against dev and prod.
"""
from alembic import op
import sqlalchemy as sa

revision = 'add_nl2sql_logs_replay_payloads'
down_revision = 'query_cap_daily'
branch_labels = None
depends_on = None

TABLE = 'nl2sql_logs'

NEW_COLUMNS = [
    ('debug_info', sa.JSON()),
    ('chart_output', sa.JSON()),
]


def _existing_columns():
    inspector = sa.inspect(op.get_bind())
    return {c['name'] for c in inspector.get_columns(TABLE)}


def upgrade():
    existing = _existing_columns()
    for name, type_ in NEW_COLUMNS:
        if name in existing:
            continue
        op.add_column(TABLE, sa.Column(name, type_, nullable=True))


def downgrade():
    existing = _existing_columns()
    for name, _type in reversed(NEW_COLUMNS):
        if name in existing:
            op.drop_column(TABLE, name)
