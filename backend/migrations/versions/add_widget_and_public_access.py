"""widgets_settings table, plus public-access policy columns on chatbot_details

Revision ID: add_widget_and_public_access
Revises: add_api_keys_agent_scope
Create Date: 2026-08-11 00:00:00.000000

The revision ID is abbreviated because `alembic_version.version_num` is `varchar(32)`: the original
`add_widget_settings_and_public_access` is 37 characters, so alembic could not record it and the
upgrade failed with StringDataRightTruncation *after* running the DDL — every attempt rolled back.
Keep new revision IDs under 32 characters.

Two things, both new to NL2SQL:

1. `widgets_settings` — per-agent appearance for the embedded widget (heading, sub-heading, greet
   message, colour, show-sources, icon and avatar URLs). Mirrors the dashboard service's table of
   the same name, including its soft-delete and audit columns, so the two stay comparable. Note the
   two services keep SEPARATE tables in separate databases: settings saved through the dashboard are
   not visible here.

2. `chatbot_details.is_public / allowed_domains / fullscreen_is_public / fullscreen_allowed_domains`
   — the public-access policy the anonymous widget GET is gated on. The dashboard asks the chat
   service for these, which 404s for any agent NL2SQL created, so NL2SQL has to own them.

Defaults are closed: both is_public flags default to FALSE, so no agent becomes publicly readable
by virtue of this migration. The allowlists are NULL, which means "any origin" — but only once the
matching flag is deliberately turned on.

Idempotent: the table, each column and each index are created only if absent, so re-running is safe.

NOTE: migrations are applied MANUALLY in this repo (the deploy job does not run them), so this must
be run by hand against dev and prod BEFORE the code that reads these columns is deployed. Adding
these fields to `models.sql_models.ChatbotDetails` means every `select(ChatbotDetails)` names them,
and PostgreSQL raises UndefinedColumn on an unmigrated database — the same trap as
`add_agent_answer_settings`, and `get_agents_list` swallows it into an empty list.

Branches from `add_api_keys_agent_scope` (where prod sits), NOT from the merge head, so applying it
does not drag in `drop_agent_voice_language`. `merge_voice_drop_api_key_scope` was repointed at this
revision to keep a single head.
"""
from alembic import op
import sqlalchemy as sa

revision = 'add_widget_and_public_access'
down_revision = 'add_api_keys_agent_scope'
branch_labels = None
depends_on = None

WIDGETS_TABLE = 'widgets_settings'
AGENT_TABLE = 'chatbot_details'

WIDGET_INDEXED_COLUMNS = ['chatbot_id', 'agent_id', 'user_id', 'deleted', 'updated_by', 'deleted_by']

AGENT_NEW_COLUMNS = [
    ('is_public', sa.Boolean(), sa.false()),
    ('allowed_domains', sa.JSON(), None),
    ('fullscreen_is_public', sa.Boolean(), sa.false()),
    ('fullscreen_allowed_domains', sa.JSON(), None),
]


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(name):
    return name in _inspector().get_table_names()


def _existing_columns(table):
    return {c['name'] for c in _inspector().get_columns(table)}


def _existing_indexes(table):
    return {i['name'] for i in _inspector().get_indexes(table)}


def upgrade():
    if not _has_table(WIDGETS_TABLE):
        op.create_table(
            WIDGETS_TABLE,
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('chatbot_id', sa.String(), nullable=True),
            sa.Column('agent_id', sa.String(), nullable=True),
            sa.Column('user_id', sa.String(), nullable=True),
            sa.Column('heading', sa.String(), nullable=True),
            sa.Column('sub_heading', sa.String(), nullable=True),
            sa.Column('greet_message', sa.String(), nullable=True),
            sa.Column('color', sa.String(), nullable=True),
            sa.Column('show_sources', sa.Boolean(), nullable=True),
            sa.Column('widget_icon', sa.String(), nullable=True),
            sa.Column('widget_avatar', sa.String(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.Column('deleted', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('updated_by', sa.String(), nullable=True),
            sa.Column('deleted_by', sa.String(), nullable=True),
            sa.Column('deleted_at', sa.DateTime(), nullable=True),
        )

    widget_indexes = _existing_indexes(WIDGETS_TABLE)
    for column in WIDGET_INDEXED_COLUMNS:
        index_name = f'ix_{WIDGETS_TABLE}_{column}'
        if index_name not in widget_indexes:
            op.create_index(index_name, WIDGETS_TABLE, [column])

    existing = _existing_columns(AGENT_TABLE)
    for name, type_, server_default in AGENT_NEW_COLUMNS:
        if name not in existing:
            op.add_column(
                AGENT_TABLE,
                sa.Column(name, type_, nullable=True, server_default=server_default),
            )


def downgrade():
    existing = _existing_columns(AGENT_TABLE)
    for name, _type, _default in reversed(AGENT_NEW_COLUMNS):
        if name in existing:
            op.drop_column(AGENT_TABLE, name)

    if _has_table(WIDGETS_TABLE):
        op.drop_table(WIDGETS_TABLE)
