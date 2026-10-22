"""api_keys: agent_id and chatbot_id, so a key can be scoped to one agent

Revision ID: add_api_keys_agent_scope
Revises: add_agent_answer_settings
Create Date: 2026-08-11 00:00:00.000000

`add_agent_id_column` (2025-11-03) listed `api_keys` among the tables to give an `agent_id`, but
prod's `api_keys` has neither `agent_id` nor `chatbot_id` — it is the only table in that list that
missed both, while alembic_version is stamped well past that revision. Nothing ever noticed because
nothing read the table: `validate_api_key` was dead code and no endpoint issued keys.

Per-agent API keys change that. `models.sql_models.ApiKeys` names both columns, so every
`select(ApiKeys)` emits them and PostgreSQL raises UndefinedColumn against an unmigrated database —
the same deploy-order trap as `add_agent_answer_settings`.

Adds:
  chatbot_id  legacy twin of agent_id, kept because readers match on either
  agent_id    the agent a key is valid for; NULL means an unscoped legacy key

Both nullable with an index each, matching how the other agent-scoped tables carry them. No
backfill: prod's api_keys is empty, and a NULL agent_id is refused by the auth path anyway.

Idempotent: each column and index is added only if absent, so this is safe to re-run.

NOTE: migrations are applied MANUALLY in this repo (the deploy job does not run them), so this must
be run by hand against dev and prod BEFORE the code that reads these columns is deployed.

Deliberately branches from `add_agent_answer_settings` rather than from the previous head
`drop_agent_voice_language`. Prod sits on `add_agent_answer_settings`, and `drop_agent_voice_language`
removes a column the currently deployed prod code still returns — chaining behind it would force that
drop on anyone applying this. The two heads are rejoined by `merge_voice_drop_api_key_scope`, which
must not be applied to prod until the code that stopped returning `voice_language` is deployed.
"""
from alembic import op
import sqlalchemy as sa

revision = 'add_api_keys_agent_scope'
down_revision = 'add_agent_answer_settings'
branch_labels = None
depends_on = None

TABLE = 'api_keys'

NEW_COLUMNS = [
    ('chatbot_id', sa.String()),
    ('agent_id', sa.String()),
]


def _inspector():
    return sa.inspect(op.get_bind())


def _existing_columns():
    return {c['name'] for c in _inspector().get_columns(TABLE)}


def _existing_indexes():
    return {i['name'] for i in _inspector().get_indexes(TABLE)}


def upgrade():
    existing = _existing_columns()
    for name, type_ in NEW_COLUMNS:
        if name not in existing:
            op.add_column(TABLE, sa.Column(name, type_, nullable=True))

    indexes = _existing_indexes()
    for name, _type in NEW_COLUMNS:
        index_name = f'ix_{TABLE}_{name}'
        if index_name not in indexes:
            op.create_index(index_name, TABLE, [name])


def downgrade():
    indexes = _existing_indexes()
    existing = _existing_columns()
    for name, _type in reversed(NEW_COLUMNS):
        index_name = f'ix_{TABLE}_{name}'
        if index_name in indexes:
            op.drop_index(index_name, TABLE)
        if name in existing:
            op.drop_column(TABLE, name)
