"""Free sample-data questions: one row per question a signed-in user asks a demo agent

Revision ID: add_demo_questions
Revises: canonicalize_legacy_table_flags
Create Date: 2026-10-23 00:00:00.000000

WHY
---
A demo agent (`chatbot_details.is_demo`) is listed for every signed-in user and runs on
FutureSmart's model key, so a visitor can try Database Agent without a key or a database.
Each visitor gets a small allowance (5 per rolling 24 hours, 20 in total) and all demo
questions together stay under a monthly spend budget.

The existing logs cannot enforce that. `nl2sql_logs` and `nl2sql_agent_health_events` are
written AFTER the answer, so two questions sent at once would both see the old count and
both run. This table is written BEFORE the model call, under a transaction-scoped advisory
lock (chatbot_management/db_utils/demo_allowance.py), so the count a question is checked
against already includes every question still running.

`chat_id` is the same id the chat logs and the health event use, so spend is read from
`nl2sql_agent_health_events.cost_usd` by joining on it: there is no second cost record.

Timestamps are UTC without a time zone, like every other table in this database.
"""
from alembic import op
import sqlalchemy as sa

revision = 'add_demo_questions'
down_revision = 'canonicalize_legacy_table_flags'
branch_labels = None
depends_on = None

TABLE = 'nl2sql_demo_questions'


def upgrade():
    if TABLE in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        TABLE,
        sa.Column('chat_id', sa.String(64), primary_key=True),
        sa.Column('user_id', sa.String(320), nullable=False),
        sa.Column('agent_id', sa.String(64), nullable=False),
        sa.Column('request_id', sa.String(64), nullable=True),
        # reserved: counted and running | answered | failed (not charged to the user)
        sa.Column('status', sa.String(16), nullable=False, server_default='reserved'),
        sa.Column('created_at', sa.DateTime(), nullable=False,
                  server_default=sa.text("(now() at time zone 'utc')")),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_nl2sql_demo_questions_user_created', TABLE, ['user_id', 'created_at'])
    op.create_index('ix_nl2sql_demo_questions_created', TABLE, ['created_at'])


def downgrade():
    op.drop_index('ix_nl2sql_demo_questions_created', table_name=TABLE)
    op.drop_index('ix_nl2sql_demo_questions_user_created', table_name=TABLE)
    op.drop_table(TABLE)
