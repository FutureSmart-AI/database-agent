"""Per-owner provider key source: bring-your-own-key or platform-managed

Revision ID: add_owner_provider_key_source
Revises: add_agent_is_demo
Create Date: 2026-10-22 00:00:00.000000

WHY
---
Until now every owner without a stored provider key - and every owner whose stored key
could not be read - was silently served by FutureSmart's platform keys. On a
bring-your-own-key deployment that is wrong twice over: the owner never learns their
key is missing, and the platform pays for work it never agreed to pay for.

`provider_key_source` makes the choice explicit, per owner:

  own       the owner's stored key or a clear error; never the platform key
  platform  the owner's key when stored, else the platform key (the old behaviour)
  NULL      the deployment default, DEFAULT_PROVIDER_KEY_SOURCE (unset = platform)

WHAT THE BACKFILL PRESERVES
---------------------------
Every owner who already has agents keeps exactly the behaviour they have today, by being
written down as `platform`:

  * existing rows are set to `platform`;
  * an agent owner with no row gets one, with the same tier and caps that
    chatbot_management/utils/owner_defaults.py answered for them before (frozen here,
    as a migration must be), plus `platform`.

So a deployment that switches its default to `own` changes behaviour only for owners who
arrive afterwards, and moving any existing owner to bring-your-own-key is one explicit
update of their row - reversible the same way.
"""

from alembic import op
import sqlalchemy as sa


revision = 'add_owner_provider_key_source'
down_revision = 'add_agent_is_demo'
branch_labels = None
depends_on = None

TABLE = 'nl2sql_owner_config'
COLUMN = 'provider_key_source'
CHECK = 'ck_nl2sql_owner_config_provider_key_source'


def _has_column(bind) -> bool:
    return COLUMN in {c['name'] for c in sa.inspect(bind).get_columns(TABLE)}


def _has_check(bind) -> bool:
    return CHECK in {c['name'] for c in sa.inspect(bind).get_check_constraints(TABLE)}


def upgrade() -> None:
    bind = op.get_bind()

    # Guarded so a re-run is a no-op rather than an error: these migrations are applied by
    # hand on prod, and a half-applied step being re-run is normal.
    if not _has_column(bind):
        op.add_column(TABLE, sa.Column(COLUMN, sa.String(), nullable=True))
    if not _has_check(bind):
        op.create_check_constraint(CHECK, TABLE, f"{COLUMN} IN ('own', 'platform')")

    op.execute(sa.text(
        f"UPDATE {TABLE} SET {COLUMN} = 'platform', updated_at = now() at time zone 'utc', "
        f"updated_by = 'migration:add_owner_provider_key_source' WHERE {COLUMN} IS NULL"))
    op.execute(sa.text(f"""
        INSERT INTO {TABLE} (owner_id, tier_type, base_tier, max_agents,
                             max_llm_tokens_per_month, max_team_members, max_queries_per_day,
                             nl2sql_enabled, created_at, updated_at, updated_by, {COLUMN})
        SELECT DISTINCT lower(d.owner_id), 'trial', NULL, 10, 1000000, 5, 20, true,
               now() at time zone 'utc', now() at time zone 'utc',
               'migration:add_owner_provider_key_source', 'platform'
        FROM chatbot_details d
        WHERE d.owner_id IS NOT NULL AND btrim(d.owner_id) <> ''
          AND NOT EXISTS (SELECT 1 FROM {TABLE} c WHERE c.owner_id = lower(d.owner_id))
    """))


def downgrade() -> None:
    bind = op.get_bind()
    # Rows inserted by the backfill stay: they carry the same caps the defaults answered,
    # so removing them would change nothing an owner can observe.
    if _has_check(bind):
        op.drop_constraint(CHECK, TABLE, type_='check')
    if _has_column(bind):
        op.drop_column(TABLE, COLUMN)
