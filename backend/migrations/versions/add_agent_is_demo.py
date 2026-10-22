"""Demo agents: one agent that appears in every signed-in user's list

Revision ID: add_agent_is_demo
Revises: add_nl2sql_logs_replay_payloads
Create Date: 2026-09-24 00:00:00.000000

WHY
---
A new user currently sees an empty agent list and cannot ask anything until they
have connected a database of their own. That is the wrong first impression for a
product whose value is visible in one question: the difference between an agent
that knows what a paying customer is and one that does not only shows when you
watch it answer.

A demo agent removes that step. It is a normal agent, owned by one account and
already connected to a database, flagged so that every signed-in user sees it in
their list at VIEWER standing - chat, messages and feedback, and nothing else.
Viewers cannot open settings, cannot read the database host or credentials, and
cannot delete it. That role already exists for invitations; this flag reuses it
rather than inventing a second idea of restricted access.

WHY A FLAG AND NOT INVITATIONS
------------------------------
The same effect is reachable today with no code at all: insert one
chatbot_invitations row per user, role viewer. It was rejected because the work
never ends - 505 rows now, one more for every future signup, and a rename or a
replacement of the demo agent means rewriting all of them. A flag is one row,
and every future user is covered by having signed in.

WHAT THIS MIGRATION DOES NOT DO
-------------------------------
It does not mark anything as a demo. The column defaults to false, so applying
this changes no behaviour for anyone until an agent is explicitly flagged. That
separation is deliberate: schema first, and the decision about which agent the
whole user base sees stays a separate, reversible act.
"""

from alembic import op
import sqlalchemy as sa


revision = 'add_agent_is_demo'
down_revision = 'add_nl2sql_logs_replay_payloads'
branch_labels = None
depends_on = None

TABLE = 'chatbot_details'
COLUMN = 'is_demo'
INDEX = 'ix_chatbot_details_is_demo'


def _has_column(bind) -> bool:
    return COLUMN in {c['name'] for c in sa.inspect(bind).get_columns(TABLE)}


def _has_index(bind) -> bool:
    return INDEX in {i['name'] for i in sa.inspect(bind).get_indexes(TABLE)}


def upgrade() -> None:
    bind = op.get_bind()

    # Guarded so a re-run is a no-op rather than an error: these migrations are
    # applied by hand on prod, and a half-applied step being re-run is normal.
    if not _has_column(bind):
        op.add_column(
            TABLE,
            # NOT NULL with a server default, so existing rows are false rather
            # than null - "is this a demo?" should never answer "unknown", and a
            # null would quietly drop the agent out of the every-user list by
            # failing the `is_demo == True` filter in a way nobody would trace.
            sa.Column(COLUMN, sa.Boolean(), nullable=False, server_default=sa.false()),
        )

    # Indexed because it is read on EVERY agent-list request, for every user, to
    # union the demo agents in. Without it that is a sequential scan of every
    # agent on the platform on the most-called screen in the product.
    if not _has_index(bind):
        op.create_index(INDEX, TABLE, [COLUMN])


def downgrade() -> None:
    bind = op.get_bind()
    if _has_index(bind):
        op.drop_index(INDEX, table_name=TABLE)
    if _has_column(bind):
        op.drop_column(TABLE, COLUMN)
