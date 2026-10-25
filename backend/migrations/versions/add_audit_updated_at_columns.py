"""Add audit updated_at/updated_by columns to dashboard-writable tables

Revision ID: add_audit_updated_at_columns
Revises: add_user_id_to_node_config
Create Date: 2026-07-15 00:00:00.000000

Completes the "who did what, and when" audit pattern on the remaining dashboard-writable
tables. Adds:
  - table_descriptions.updated_at
  - few_shot_examples.updated_at
  - chat_sessions.updated_at
  - chatbot_details.updated_at
  - chatbot_details.updated_by  (acting dashboard user on last edit; distinct from owner_id)

All columns are nullable — internal / API-key (master) calls leave the actor NULL; updated_at
is set by the app on every write. NOTE: migrations are applied MANUALLY in this repo (the
deploy job does not run them), so this must be run by hand against dev and prod.
"""
from alembic import op
import sqlalchemy as sa

revision = 'add_audit_updated_at_columns'
down_revision = 'add_user_id_to_node_config'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('table_descriptions', sa.Column('updated_at', sa.DateTime(), nullable=True))
    op.add_column('few_shot_examples', sa.Column('updated_at', sa.DateTime(), nullable=True))
    op.add_column('chat_sessions', sa.Column('updated_at', sa.DateTime(), nullable=True))
    op.add_column('chatbot_details', sa.Column('updated_at', sa.DateTime(), nullable=True))
    op.add_column('chatbot_details', sa.Column('updated_by', sa.String(), nullable=True))
    op.create_index('ix_chatbot_details_updated_by', 'chatbot_details', ['updated_by'])


def downgrade():
    op.drop_index('ix_chatbot_details_updated_by', 'chatbot_details')
    op.drop_column('chatbot_details', 'updated_by')
    op.drop_column('chatbot_details', 'updated_at')
    op.drop_column('chat_sessions', 'updated_at')
    op.drop_column('few_shot_examples', 'updated_at')
    op.drop_column('table_descriptions', 'updated_at')
