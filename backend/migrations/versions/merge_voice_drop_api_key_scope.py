"""Rejoin the two heads: voice_language drop and api_keys agent scope

Revision ID: merge_voice_drop_api_key_scope
Revises: drop_agent_voice_language, add_invitation_roles
Create Date: 2026-08-11 00:00:00.000000

`add_api_keys_agent_scope` branches from `add_agent_answer_settings` on purpose, so that adding
per-agent API key columns does not drag `drop_agent_voice_language` along with it — prod is on
that branch and its running code still returns `voice_language`. `add_widget_and_public_access` and
`add_invitation_roles` continue the same branch.

That leaves two heads. This merge rejoins them and does no schema work of its own.

⚠ Applying this (or any `alembic upgrade head`) runs `drop_agent_voice_language`, which removes
`chatbot_details.voice_language`. Do that only once the deployed code no longer reads or returns
that column, otherwise `GET /config` breaks. Until then, upgrade to `add_api_keys_agent_scope`
explicitly rather than to `head`.
"""
from alembic import op
import sqlalchemy as sa

revision = 'merge_voice_drop_api_key_scope'
down_revision = ('drop_agent_voice_language', 'add_invitation_roles')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
