"""Per-owner NL2SQL configuration

Revision ID: add_nl2sql_owner_config
Revises: add_user_provider_keys
Create Date: 2026-08-19 00:00:00.000000

One new table, `nl2sql_owner_config` — this service's own per-owner tier, caps and
on/off switch.

A DELIBERATE SUBSET of fs-agent-usage-limits' `owner_configurations` +
`owner_platform_limits`. Only fields NL2SQL can answer for itself are carried over, and
each kept cap is countable from this database:

    max_agents                 -> chatbot_details
    max_llm_tokens_per_month   -> nl2sql_agent_health_events
    max_team_members           -> chatbot_invitations

Left behind on purpose:

    max_indexed_characters, max_file_size_mb          the knowledge service's numbers
    max_conversations_per_month, max_messages_...     the chat service counts these
    enabled_services for the other five services     not NL2SQL's to answer; six services
                                                     each keeping a copy would give six
                                                     answers to one question
    default_models                                   NL2SQL already has better — per-node
                                                     models in chatbot_node_config plus
                                                     model_config.json

NULL on a cap means unlimited, matching the usage service. An owner with NO ROW is normal:
reads fall back to `chatbot_management/utils/owner_defaults.py`, so a customer who has
never been configured is usable immediately rather than a 404. That is why nothing is
seeded here.

NOTE the caps are a COPY of the platform's, not a mirror — nothing syncs them. A customer
on "10 agents" gets 10 here and 10 in every other service that does the same. If limits
must stay platform-wide, this table should be fed by a periodic sync from the usage
service instead of edited directly.

Revision IDs are kept under 32 characters — `alembic_version.version_num` is
`varchar(32)`, and a longer id fails the upgrade *after* the DDL has run.

Idempotent: created only if absent, so re-running is safe.

NOTE: migrations are applied MANUALLY in this repo (the deploy job does not run them).
"""
from alembic import op
import sqlalchemy as sa

revision = 'add_nl2sql_owner_config'
down_revision = 'add_user_provider_keys'
branch_labels = None
depends_on = None

TABLE = 'nl2sql_owner_config'


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(name):
    return name in _inspector().get_table_names()


def upgrade():
    if _has_table(TABLE):
        return
    op.create_table(
        TABLE,
        # The owner's email, lower-cased — matches chatbot_details.owner_id, which this
        # database stores lower-case throughout.
        sa.Column('owner_id', sa.String(), primary_key=True, nullable=False),
        sa.Column('tier_type', sa.String(), nullable=False, server_default='trial'),
        # Only set for custom tiers.
        sa.Column('base_tier', sa.String(), nullable=True),
        # Caps. NULL = unlimited.
        sa.Column('max_agents', sa.Integer(), nullable=True),
        sa.Column('max_llm_tokens_per_month', sa.Integer(), nullable=True),
        sa.Column('max_team_members', sa.Integer(), nullable=True),
        # Whether NL2SQL is enabled for this owner at all.
        sa.Column('nl2sql_enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('nl2sql_enabled_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        # Acting dashboard user on the last edit — same convention as the rest of this repo.
        sa.Column('updated_by', sa.String(), nullable=True),
    )
    op.create_index('ix_nl2sql_owner_config_updated_by', TABLE, ['updated_by'])


def downgrade():
    if _has_table(TABLE):
        op.drop_table(TABLE)
