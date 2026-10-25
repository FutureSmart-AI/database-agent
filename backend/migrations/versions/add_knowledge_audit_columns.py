"""Add updated_by/deleted_at/deleted_by to the knowledge + node-config tables

Revision ID: add_knowledge_audit_columns
Revises: add_delete_audit_columns
Create Date: 2026-08-07 00:00:00.000000

Extends the "who did what, and when" audit pattern to the three remaining tables that
record dashboard writes: table_descriptions, few_shot_examples and chatbot_node_config.

Until now these tables carried a single `user_id` that did double duty — the creator on
insert, then overwritten with the last dashboard editor on update. That conflation makes
"who created this" unanswerable once a second user edits the row. `updated_by` splits the
two: `user_id` keeps its creator meaning, `updated_by` carries the acting user on the most
recent edit (matching the chatbot_details / chat_sessions convention).

`deleted_at` / `deleted_by` record the actor on a delete for the rows that survive one.

All columns are nullable: internal / API-key (master) calls and background jobs (HC
profiling, description generation) leave the actor NULL by design, so a NULL means "not a
dashboard user", not "missing data".

No backfill. The pre-existing `user_id` cannot be split into creator-vs-editor after the
fact — for any row written before this migration we do not know whether it holds the
creator or a later editor, so asserting either into `updated_by` would invent audit data.
`updated_by` populates going forward on the next dashboard write to each row.

NOTE: migrations are applied MANUALLY in this repo (the deploy job does not run them), so
this must be run by hand against dev and prod.
"""
from alembic import op
import sqlalchemy as sa

revision = 'add_knowledge_audit_columns'
down_revision = 'add_delete_audit_columns'
branch_labels = None
depends_on = None

# table -> whether the table needs an index on the actor columns
_TABLES = ('table_descriptions', 'few_shot_examples', 'chatbot_node_config')


def upgrade():
    for table in _TABLES:
        op.add_column(table, sa.Column('updated_by', sa.String(), nullable=True))
        op.create_index(f'ix_{table}_updated_by', table, ['updated_by'])
        op.add_column(table, sa.Column('deleted_at', sa.DateTime(), nullable=True))
        op.add_column(table, sa.Column('deleted_by', sa.String(), nullable=True))
        op.create_index(f'ix_{table}_deleted_by', table, ['deleted_by'])


def downgrade():
    for table in _TABLES:
        op.drop_index(f'ix_{table}_deleted_by', table)
        op.drop_column(table, 'deleted_by')
        op.drop_column(table, 'deleted_at')
        op.drop_index(f'ix_{table}_updated_by', table)
        op.drop_column(table, 'updated_by')
