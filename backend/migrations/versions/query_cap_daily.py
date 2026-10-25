"""Query cap becomes daily: rename max_queries_per_month -> max_queries_per_day

Revision ID: query_cap_daily
Revises: add_owner_query_cap
Create Date: 2026-08-20 00:00:00.000000

The cap shipped as a calendar-month allowance. The requirement is 20 messages per DAY per
owner, resetting 24 hours after being hit, so the column is renamed rather than
reinterpreted -- a column called `max_queries_per_month` enforcing a daily limit is a trap
for whoever reads it next.

WINDOW: rolling 24 hours, not a calendar day. "Resets 24 hours after being hit" is exactly
what a rolling window does -- the allowance returns as turns age out -- and it needs no
reset job and has no midnight cliff where a whole allowance reappears at once.
`GET /v1/owners/{owner_id}/usage/status` reports `queries_reset_at`, the moment the oldest
counted turn ages out.

SCOPE: per owner, across every agent they own AND their CSV-agent turns. Ten agents share
one allowance of 20; they do not get 20 each.

VALUES ARE RESTATED AS 20/DAY. add_owner_query_cap seeded every owner with 20 as a monthly
figure. Carrying those over unchanged would silently turn a monthly allowance into a daily
one, so every row is set to the daily default explicitly. Owners deliberately set to
unlimited (NULL) keep that -- a decision to exempt someone should survive a rename.

Renaming is safe here: the column shipped hours before this, is master-key only, and has no
caller outside this service.

Revision IDs stay under 32 characters -- `alembic_version.version_num` is `varchar(32)`,
and a longer id fails the upgrade *after* the DDL has run.

NOTE: migrations are applied MANUALLY in this repo (the deploy job does not run them).
Apply BEFORE deploying, or every chat request logs a cap-lookup error against the missing
column. Chat keeps working -- the check fails open -- but nothing is enforced until this
runs.
"""
from alembic import op
import sqlalchemy as sa

revision = 'query_cap_daily'
down_revision = 'add_owner_query_cap'
branch_labels = None
depends_on = None

TABLE = 'nl2sql_owner_config'
OLD = 'max_queries_per_month'
NEW = 'max_queries_per_day'
DEFAULT_CAP = 20  # keep in step with owner_defaults.DEFAULT_LIMITS


def _columns():
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns(TABLE)}


def upgrade():
    cols = _columns()
    if NEW not in cols:
        if OLD in cols:
            op.alter_column(TABLE, OLD, new_column_name=NEW)
        else:
            # add_owner_query_cap never ran here (a fresh database, or an environment set
            # up after this rename). Create the column directly.
            op.add_column(TABLE, sa.Column(NEW, sa.Integer(), nullable=True))

    bind = op.get_bind()

    # Restate the default as a DAILY figure. `is not null` keeps deliberate unlimited rows.
    reset = bind.execute(sa.text(
        f"update {TABLE} set {NEW} = {DEFAULT_CAP}, updated_at = now() "
        f"where {NEW} is not null and {NEW} <> {DEFAULT_CAP}"
    )).rowcount

    seeded = bind.execute(sa.text(f"""
        insert into {TABLE} (owner_id, tier_type, max_agents, max_team_members,
                             max_llm_tokens_per_month, {NEW}, created_at, updated_at)
        select distinct d.owner_id, 'trial', 10, 5, 1000000, {DEFAULT_CAP}, now(), now()
        from chatbot_details d
        where d.owner_id is not null and d.deleted = false
        on conflict (owner_id) do nothing
    """)).rowcount

    print(f"[query_cap_daily] {OLD} -> {NEW}; {seeded} owner(s) seeded, "
          f"{reset} restated to {DEFAULT_CAP}/day")


def downgrade():
    if NEW in _columns():
        op.alter_column(TABLE, NEW, new_column_name=OLD)
