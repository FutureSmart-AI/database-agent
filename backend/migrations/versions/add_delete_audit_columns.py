"""Add delete-audit columns (deleted_at/deleted_by) and chat_sessions.updated_by

Revision ID: add_delete_audit_columns
Revises: add_audit_updated_at_columns
Create Date: 2026-08-06 00:00:00.000000

Extends the "who did what, and when" audit pattern to soft deletes. Before this, a soft
delete recorded only the `deleted` flag (plus chatbot_details.deleted_at) — never the actor.
Adds:
  - chatbot_details.deleted_by  (acting dashboard user on the soft delete)
  - chat_sessions.updated_by    (acting dashboard user on the last edit, e.g. rename)
  - chat_sessions.deleted_at
  - chat_sessions.deleted_by

All columns are nullable — internal / API-key (master) calls leave the actor NULL, and rows
soft-deleted before this migration keep NULL for both new delete columns (the actor was never
recorded, so it cannot be backfilled). NOTE: migrations are applied MANUALLY in this repo (the
deploy job does not run them), so this must be run by hand against dev and prod.
"""
from alembic import op
import sqlalchemy as sa

revision = 'add_delete_audit_columns'
down_revision = 'add_audit_updated_at_columns'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('chatbot_details', sa.Column('deleted_by', sa.String(), nullable=True))
    op.create_index('ix_chatbot_details_deleted_by', 'chatbot_details', ['deleted_by'])

    op.add_column('chat_sessions', sa.Column('updated_by', sa.String(), nullable=True))
    op.create_index('ix_chat_sessions_updated_by', 'chat_sessions', ['updated_by'])
    op.add_column('chat_sessions', sa.Column('deleted_at', sa.DateTime(), nullable=True))
    op.add_column('chat_sessions', sa.Column('deleted_by', sa.String(), nullable=True))
    op.create_index('ix_chat_sessions_deleted_by', 'chat_sessions', ['deleted_by'])


def downgrade():
    op.drop_index('ix_chat_sessions_deleted_by', 'chat_sessions')
    op.drop_column('chat_sessions', 'deleted_by')
    op.drop_column('chat_sessions', 'deleted_at')
    op.drop_index('ix_chat_sessions_updated_by', 'chat_sessions')
    op.drop_column('chat_sessions', 'updated_by')

    op.drop_index('ix_chatbot_details_deleted_by', 'chatbot_details')
    op.drop_column('chatbot_details', 'deleted_by')
