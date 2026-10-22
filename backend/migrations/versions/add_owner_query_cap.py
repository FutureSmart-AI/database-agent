"""Monthly query cap per owner

Revision ID: add_owner_query_cap
Revises: add_usage_events
Create Date: 2026-08-20 00:00:00.000000

Adds `nl2sql_owner_config.max_queries_per_month` -- the first limit this service actually
ENFORCES. Chat is refused with 429 once an owner passes it (see
`api/v1/routers/chat.py`).

NULL means unlimited. Owners with no row at all fall back to the default in
`chatbot_management/utils/owner_defaults.py`, which is 20.

WHY THIS MIGRATION WRITES DATA, NOT JUST A COLUMN
The cap has to apply to owners who already exist, not only to ones created from here on,
so every owner holding an agent is given an explicit row at the default of 20. That is a
deliberate choice with an immediate effect: owners already past 20 queries this month are
refused on their next question until someone raises their cap. As of this migration that
is 4 of the 10 active owners -- one at 2,403 queries for the month, then 84, 38 and 24.

To lift the cap for an owner:
    PATCH /v1/owners/{owner_id}/config {"platform_limits": {"max_queries_per_month": 500}}
    PATCH /v1/owners/{owner_id}/config {"platform_limits": {"max_queries_per_month": null}}
        -- null removes the cap entirely.

COUNTING comes from `nl2sql_logs` joined to `chatbot_details.owner_id`, not from
`nl2sql_agent_health_events`. The health table only starts 2026-08-13 and reported 16
queries for an owner who had actually asked 2,403 -- capping against it would let someone
past by a factor of 150. `nl2sql_logs` is the canonical per-turn record.

The window is the calendar month to date, matching `max_llm_tokens_per_month`.

Revision IDs stay under 32 characters -- `alembic_version.version_num` is `varchar(32)`,
and a longer id fails the upgrade *after* the DDL has run.

Idempotent: the column is added only if absent; the seed inserts only owners with no row;
the backfill only fills rows where the cap is still unset.

NOTE: migrations are applied MANUALLY in this repo (the deploy job does not run them).
Apply BEFORE deploying the enforcement. If the code ships first, the cap lookup errors on
every chat request -- it fails open, so chat keeps working, but every request logs an error.
"""
from alembic import op
import sqlalchemy as sa

revision = 'add_owner_query_cap'
down_revision = 'add_usage_events'
branch_labels = None
depends_on = None

TABLE = 'nl2sql_owner_config'
COLUMN = 'max_queries_per_month'
DEFAULT_CAP = 20  # keep in step with owner_defaults.DEFAULT_LIMITS

# Give every owner that already holds an agent a configuration row at the default cap.
# ON CONFLICT DO NOTHING leaves owners who already have a row to the backfill below.
SEED_SQL = f"""
insert into {TABLE} (owner_id, tier_type, max_agents, max_team_members,
                     max_llm_tokens_per_month, {COLUMN}, created_at, updated_at)
select distinct d.owner_id, 'trial', 10, 5, 1000000, {DEFAULT_CAP}, now(), now()
from chatbot_details d
where d.owner_id is not null
  and d.deleted = false
on conflict (owner_id) do nothing
"""

# Owners who already had a configuration row (set before this column existed) get the same
# default. Rows deliberately set to unlimited AFTER this migration runs are never touched,
# because the migration runs once.
BACKFILL_SQL = f"""
update {TABLE}
   set {COLUMN} = {DEFAULT_CAP}, updated_at = now()
 where {COLUMN} is null
"""


def _columns():
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns(TABLE)}


def upgrade():
    if COLUMN not in _columns():
        # Nullable, no server default: NULL = unlimited.
        op.add_column(TABLE, sa.Column(COLUMN, sa.Integer(), nullable=True))

    bind = op.get_bind()
    seeded = bind.execute(sa.text(SEED_SQL)).rowcount
    filled = bind.execute(sa.text(BACKFILL_SQL)).rowcount
    print(f"[add_owner_query_cap] capped {seeded} new + {filled} existing owner(s) "
          f"at {DEFAULT_CAP} queries/month")


def downgrade():
    # The seeded rows are left in place: apart from the cap they carry the same values the
    # defaults would have produced, so dropping the column is enough to undo the cap.
    if COLUMN in _columns():
        op.drop_column(TABLE, COLUMN)
