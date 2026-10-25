"""chatbot_details: follow-up, voice and suggested-question answer settings

Revision ID: add_agent_answer_settings
Revises: add_connection_owner_fix_source
Create Date: 2026-08-10 00:00:00.000000

The NL2SQL dashboard's Settings screen owns a set of answer settings per agent. Most already had
columns here (show_sql_query, show_db_result, graph_output, allowed_graphs, debug_info); these five
did not, so the toggles had nowhere to persist and the UI could only keep them in browser state:

  follow_up             suggest follow-up questions after an answer
  voice_input_enabled   show the microphone in the ask box
  voice_output_enabled  offer "Listen" on an answer
  voice_language        BCP-47 tag for speech in and out, or "auto" to detect
  suggested_questions   starter questions shown before the first message

Defaults are the off/empty state so existing agents keep behaving exactly as they do now — the
runtime treats NULL as the documented default in either case.

Idempotent: each column is added only if absent, so this is safe to re-run.

NOTE: migrations are applied MANUALLY in this repo (the deploy job does not run them), so this
must be run by hand against dev and prod.
"""
from alembic import op
import sqlalchemy as sa

revision = 'add_agent_answer_settings'
down_revision = 'add_connection_owner_fix_source'
branch_labels = None
depends_on = None

TABLE = 'chatbot_details'

NEW_COLUMNS = [
    ('follow_up', sa.Boolean(), sa.false()),
    ('voice_input_enabled', sa.Boolean(), sa.false()),
    ('voice_output_enabled', sa.Boolean(), sa.false()),
    ('voice_language', sa.String(), None),
    ('suggested_questions', sa.JSON(), None),
]


def _existing_columns():
    inspector = sa.inspect(op.get_bind())
    return {c['name'] for c in inspector.get_columns(TABLE)}


def upgrade():
    existing = _existing_columns()
    for name, type_, server_default in NEW_COLUMNS:
        if name in existing:
            continue
        op.add_column(TABLE, sa.Column(name, type_, nullable=True, server_default=server_default))


def downgrade():
    existing = _existing_columns()
    for name, _type, _default in reversed(NEW_COLUMNS):
        if name in existing:
            op.drop_column(TABLE, name)
