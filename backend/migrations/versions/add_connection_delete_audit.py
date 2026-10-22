"""Audit database deletion: soft-delete + actor columns on chatbot_connection

Revision ID: add_connection_delete_audit
Revises: add_knowledge_audit_columns
Create Date: 2026-08-07 00:00:00.000000

Deleting a database removed the chatbot_connection row outright, so there was nothing left
to record who did it or when. The row is now retained as a tombstone:

  - deleted     flag readers filter on (matches the chatbot_details soft-delete convention)
  - deleted_at  when the database was detached
  - deleted_by  acting dashboard user who detached it
  - updated_by  acting dashboard user on the last edit to the connection

`updated_by` is included because chatbot_connection.user_id is owner-semantics — set once at
creation and deliberately never overwritten — so edits to a connection (host, credentials,
description) previously had no actor recorded at all.

`deleted` is NOT NULL with a server default of false so existing rows read as live.

Credentials are NOT retained on a tombstone: the delete blanks db_password, since keeping a
live password for a database the user detached is a liability the audit trail does not need.
The connection identity (host / name / engine) is kept, which is what makes the record
meaningful. Per-DB metadata is still purged on delete, so a tombstone is a shell row.

NOTE: migrations are applied MANUALLY in this repo (the deploy job does not run them), so
this must be run by hand against dev and prod.
"""
from alembic import op
import sqlalchemy as sa

revision = 'add_connection_delete_audit'
down_revision = 'add_knowledge_audit_columns'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('chatbot_connection', sa.Column('updated_by', sa.String(), nullable=True))
    op.create_index('ix_chatbot_connection_updated_by', 'chatbot_connection', ['updated_by'])

    op.add_column(
        'chatbot_connection',
        sa.Column('deleted', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column('chatbot_connection', sa.Column('deleted_at', sa.DateTime(), nullable=True))
    op.add_column('chatbot_connection', sa.Column('deleted_by', sa.String(), nullable=True))
    op.create_index('ix_chatbot_connection_deleted_by', 'chatbot_connection', ['deleted_by'])
    op.create_index('ix_chatbot_connection_deleted', 'chatbot_connection', ['deleted'])


def downgrade():
    op.drop_index('ix_chatbot_connection_deleted', 'chatbot_connection')
    op.drop_index('ix_chatbot_connection_deleted_by', 'chatbot_connection')
    op.drop_column('chatbot_connection', 'deleted_by')
    op.drop_column('chatbot_connection', 'deleted_at')
    op.drop_column('chatbot_connection', 'deleted')

    op.drop_index('ix_chatbot_connection_updated_by', 'chatbot_connection')
    op.drop_column('chatbot_connection', 'updated_by')
