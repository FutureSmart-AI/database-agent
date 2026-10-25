"""chatbot_connection: explicit owner_id + correct mislabelled description_source

Revision ID: add_connection_owner_fix_source
Revises: add_connection_delete_audit
Create Date: 2026-08-07 00:00:00.000000

Two fixes to chatbot_connection, both raised in QA:

1. owner_id was missing, so identifying an agent's owner from a connection row meant joining
   chatbot_details — awkward in shared-agent scenarios. The multi-DB add path did store the
   owner's email, but in `user_id`, whose documented meaning is "creator". This adds an
   explicit owner_id and backfills it from chatbot_details.owner_id via agent_id (falling
   back to chatbot_id for legacy rows). Rows whose agent has no owner_id stay NULL — there
   is nothing to copy and inventing one would be false audit data.

2. add_description_provenance backfilled EVERY row that already had a description as
   description_source='manual', including descriptions that were auto-generated. The real
   source is recoverable: description_generation_jobs retains the generated text per db_id,
   so a connection whose current description matches a completed job's output was auto-
   generated. Those rows are corrected to 'auto'. Rows with no matching completed job are
   left as 'manual' — absence of a job record is not evidence of auto-generation.

Both steps are idempotent and safe to re-run.

NOTE: migrations are applied MANUALLY in this repo (the deploy job does not run them), so
this must be run by hand against dev and prod.
"""
from alembic import op
import sqlalchemy as sa

revision = 'add_connection_owner_fix_source'
down_revision = 'add_connection_delete_audit'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('chatbot_connection', sa.Column('owner_id', sa.String(), nullable=True))
    op.create_index('ix_chatbot_connection_owner_id', 'chatbot_connection', ['owner_id'])

    # 1) Backfill the owner from the agent record.
    op.execute("""
        UPDATE chatbot_connection c
        SET owner_id = d.owner_id
        FROM chatbot_details d
        WHERE d.agent_id = COALESCE(c.agent_id, c.chatbot_id)
          AND d.owner_id IS NOT NULL
          AND c.owner_id IS NULL
    """)

    # 2) Correct descriptions that were auto-generated but backfilled as 'manual'.
    op.execute("""
        UPDATE chatbot_connection c
        SET description_source = 'auto'
        WHERE c.description_source = 'manual'
          AND c.description IS NOT NULL
          AND btrim(c.description) <> ''
          AND EXISTS (
              SELECT 1 FROM description_generation_jobs j
              WHERE j.db_id = c.db_id
                AND j.status = 'done'
                AND btrim(j.description) = btrim(c.description)
          )
    """)


def downgrade():
    # description_source is not reverted: the pre-migration value ('manual') was itself
    # incorrect for these rows, so restoring it would reintroduce the bad data.
    op.drop_index('ix_chatbot_connection_owner_id', 'chatbot_connection')
    op.drop_column('chatbot_connection', 'owner_id')
