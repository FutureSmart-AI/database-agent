"""chatbot_details: drop voice_language — a setting no UI ever asked for

Revision ID: drop_agent_voice_language
Revises: add_agent_answer_settings
Create Date: 2026-08-11 00:00:00.000000

add_agent_answer_settings introduced voice_language alongside voice_input_enabled and
voice_output_enabled. The two enabled flags map to controls that exist on the Settings screen;
voice_language did not — it was added from an acceptance criterion ("set the default spoken
language") rather than from a real control or an agreed field name. Carrying an unused column on
chatbot_details is how schemas rot, so it comes back out.

Nothing read it: the column was only ever echoed by GET /v1/agents/{id}/config and accepted by
PATCH …/config/params, never consulted at query time. Dropping it loses no behaviour. Any value a
caller managed to store is discarded, which is why the downgrade cannot restore data — only the
column.

If a language picker is ever built, re-add it then, named to match whatever the UI actually calls it.

Idempotent: the column is dropped only if present, so this is safe to re-run.

NOTE: migrations are applied MANUALLY in this repo (the deploy job does not run them), so this
must be run by hand against dev and prod.
"""
from alembic import op
import sqlalchemy as sa

revision = 'drop_agent_voice_language'
down_revision = 'add_agent_answer_settings'
branch_labels = None
depends_on = None

TABLE = 'chatbot_details'
COLUMN = 'voice_language'


def _has_column():
    inspector = sa.inspect(op.get_bind())
    return COLUMN in {c['name'] for c in inspector.get_columns(TABLE)}


def upgrade():
    if _has_column():
        op.drop_column(TABLE, COLUMN)


def downgrade():
    # Restores the column, not its contents — the data is gone by design.
    if not _has_column():
        op.add_column(TABLE, sa.Column(COLUMN, sa.String(), nullable=True))
