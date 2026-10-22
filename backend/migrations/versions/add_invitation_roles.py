"""Roles and audit columns on chatbot_invitations, so NL2SQL owns sharing itself

Revision ID: add_invitation_roles
Revises: add_widget_and_public_access
Create Date: 2026-08-12 00:00:00.000000

Sharing has so far been the chat service's: it keeps its own `agent_invitations` table, with a
`role` per collaborator, and answers `/auth/check-access` from it. NL2SQL is taking sharing over,
so the same information has to exist here. Rather than a second table, this extends the
`chatbot_invitations` we already have — it holds real rows and five modules already read it
(`session/db_utils`, `agent/db_utils/common_db_utils`, `chatbot_management/db_utils/bot_crud_db_utils`
among them), all of which keep working unchanged.

What it adds:

1. `role` — `viewer` or `editor`, defaulting to `viewer`. This is the field the Share screen's
   role dropdown writes and `get_agent_access_role` reads.
2. `updated_at` / `updated_by` — who last changed a collaborator's role, matching the audit
   columns already carried by `chatbot_details`, `chatbot_connection` and the rest.

And three data changes the above depends on:

3. Emails are lowercased in place. Role resolution matches on the email, and a row stored as
   `Foo@x.com` would never match a caller who signs in as `foo@x.com` — the invited user would
   appear invited but be denied every role.
4. `agent_id` is backfilled from `chatbot_details.chatbot_id` where it is NULL. Legacy rows carry
   only `chatbot_id`, so the v1 endpoints — which are all keyed on `agent_id` — cannot see them.
   Existing shares would silently vanish from the new Share screen.
5. A unique index on `(agent_id, lower(invited_user_email))` so the same person cannot be invited
   twice to one agent. Duplicates already in the table are collapsed to the earliest row first,
   otherwise the index cannot be created. Rows with a NULL `agent_id` are unaffected (NULLs are
   distinct in PostgreSQL), so anything step 4 could not resolve is simply left alone.

⚠ EXISTING COLLABORATORS BECOME `viewer`. There is no role information in this table today, so
every pre-existing row takes the default. Nothing changes behaviourally: the role is reported to
the dashboard but nothing authorizes on it — `require_agent_permission` admits any valid login
regardless. Should that ever change, these defaults have to be reviewed first, or a collaborator
who was an editor elsewhere silently loses write access.

Idempotent: every column, index and data statement is guarded or naturally re-runnable.

NOTE: migrations are applied MANUALLY in this repo (the deploy job does not run them), so this must
be run by hand against dev and prod BEFORE the code that reads these columns is deployed. Adding
these fields to `models.sql_models.ChatbotInvitations` makes every `select(ChatbotInvitations)`
name them, and PostgreSQL raises UndefinedColumn on an unmigrated database — the same trap as
`add_agent_answer_settings`. Here it would break session listing and agent deletion, not just one
endpoint.

Branches from `add_widget_and_public_access` (the branch prod is on), NOT from the merge head, so
applying it does not drag in `drop_agent_voice_language`. `merge_voice_drop_api_key_scope` is
repointed at this revision to keep a single head.

Keep the revision ID under 32 characters — `alembic_version.version_num` is `varchar(32)`, and a
longer one fails at the very end of an otherwise successful upgrade.
"""
from alembic import op
import sqlalchemy as sa

revision = 'add_invitation_roles'
down_revision = 'add_widget_and_public_access'
branch_labels = None
depends_on = None

TABLE = 'chatbot_invitations'

NEW_COLUMNS = [
    ('role', sa.String(), sa.text("'viewer'")),
    ('updated_at', sa.DateTime(), None),
    ('updated_by', sa.String(), None),
]

UNIQUE_INDEX = 'uq_chatbot_invitations_agent_email'
LOWER_EMAIL_INDEX = 'ix_chatbot_invitations_invited_user_email_lower'
UPDATED_BY_INDEX = 'ix_chatbot_invitations_updated_by'


def _inspector():
    return sa.inspect(op.get_bind())


def _existing_columns(table):
    return {c['name'] for c in _inspector().get_columns(table)}


def upgrade():
    existing = _existing_columns(TABLE)
    for name, type_, server_default in NEW_COLUMNS:
        if name not in existing:
            op.add_column(
                TABLE,
                sa.Column(name, type_, nullable=True, server_default=server_default),
            )

    # Lowercase before anything matches on the email — see (3) above.
    op.execute(
        f"""
        UPDATE {TABLE}
        SET invited_user_email = lower(trim(invited_user_email))
        WHERE invited_user_email IS NOT NULL
          AND invited_user_email <> lower(trim(invited_user_email))
        """
    )
    op.execute(
        f"""
        UPDATE {TABLE}
        SET invited_by_email = lower(trim(invited_by_email))
        WHERE invited_by_email IS NOT NULL
          AND invited_by_email <> lower(trim(invited_by_email))
        """
    )

    # Legacy rows carry only chatbot_id; the v1 API is keyed on agent_id — see (4) above.
    op.execute(
        f"""
        UPDATE {TABLE} AS i
        SET agent_id = d.agent_id
        FROM chatbot_details AS d
        WHERE i.agent_id IS NULL
          AND i.chatbot_id = d.chatbot_id
          AND d.agent_id IS NOT NULL
        """
    )

    # Collapse duplicates to the earliest invitation, so the unique index below can be created.
    op.execute(
        f"""
        DELETE FROM {TABLE} AS a
        USING {TABLE} AS b
        WHERE a.agent_id IS NOT NULL
          AND a.agent_id = b.agent_id
          AND lower(a.invited_user_email) = lower(b.invited_user_email)
          AND a.invitation_id > b.invitation_id
        """
    )

    op.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS {UNIQUE_INDEX} "
        f"ON {TABLE} (agent_id, lower(invited_user_email))"
    )
    # Role resolution looks the caller up by email on every authorized request.
    op.execute(
        f"CREATE INDEX IF NOT EXISTS {LOWER_EMAIL_INDEX} "
        f"ON {TABLE} (lower(invited_user_email))"
    )
    op.execute(f"CREATE INDEX IF NOT EXISTS {UPDATED_BY_INDEX} ON {TABLE} (updated_by)")

    # Existing rows predate the column and take the default explicitly, so a NULL role never
    # reaches role resolution.
    op.execute(f"UPDATE {TABLE} SET role = 'viewer' WHERE role IS NULL")


def downgrade():
    # The lowercasing, the agent_id backfill and the de-duplication are not reversed — the
    # original casing and the removed duplicate rows are not recorded anywhere.
    op.execute(f"DROP INDEX IF EXISTS {UPDATED_BY_INDEX}")
    op.execute(f"DROP INDEX IF EXISTS {LOWER_EMAIL_INDEX}")
    op.execute(f"DROP INDEX IF EXISTS {UNIQUE_INDEX}")

    existing = _existing_columns(TABLE)
    for name, _type, _default in reversed(NEW_COLUMNS):
        if name in existing:
            op.drop_column(TABLE, name)
