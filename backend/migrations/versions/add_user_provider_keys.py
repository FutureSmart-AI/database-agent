"""Owner provider credentials (BYOK) owned by NL2SQL

Revision ID: add_user_provider_keys
Revises: add_agent_health_events
Create Date: 2026-08-18 00:00:00.000000

One new table, `user_provider_keys` — NL2SQL's own copy of the owner credential store.
Ported from fs-agent-usage-limits (`services/database_models_credentials.py`).

Every LLM node asks for the owner's own provider key before falling back to the platform
key. That lookup was an HTTP GET to the usage service on each call from 20 call sites;
NL2SQL now reads this table.

The plaintext key is never stored. Three columns stand in for it:
  encrypted_key  Fernet ciphertext, readable only with APP_MASTER_KEY
  key_hash       HMAC-SHA256 with HASH_SALT — duplicate detection without decrypting,
                 and not reversible to the key
  key_mask       "sk-...48sA" for display, so the UI never handles the real key

UNIQUE (owner_id, provider) is the upsert target. Without it two live keys could exist
for one provider and which one got used would be non-deterministic.

BEFORE COPYING ROWS from the usage service: APP_MASTER_KEY and HASH_SALT must match that
service's values exactly. Different key material makes copied ciphertext permanently
undecryptable — and because the credential lookup falls back to the platform key on
failure, that surfaces as owners' usage being billed to the platform rather than as an
error. Verify a decrypt round-trip on one row before trusting a bulk copy.

Revision IDs are kept under 32 characters — `alembic_version.version_num` is
`varchar(32)`, and a longer id fails the upgrade *after* the DDL has run.

Idempotent: table and indexes are created only if absent, so re-running is safe.

NOTE: migrations are applied MANUALLY in this repo (the deploy job does not run them).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'add_user_provider_keys'
down_revision = 'add_agent_health_events'
branch_labels = None
depends_on = None

TABLE = 'user_provider_keys'


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(name):
    return name in _inspector().get_table_names()


def _existing_indexes(table):
    return {i['name'] for i in _inspector().get_indexes(table)}


def upgrade():
    if not _has_table(TABLE):
        op.create_table(
            TABLE,
            sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            # The owner the key belongs to — an email, matching chatbot_details.owner_id.
            sa.Column('owner_id', sa.String(255), nullable=False),
            # Provider slug: openai | anthropic | groq | google | deepseek | minimax | ...
            sa.Column('provider', sa.String(100), nullable=False),
            sa.Column('encrypted_key', sa.Text(), nullable=False),
            # 64-char hex HMAC-SHA256. Duplicate detection only, never a lookup key.
            sa.Column('key_hash', sa.String(64), nullable=False),
            sa.Column('key_mask', sa.String(50), nullable=False),
            # Result of the live provider check at write time. A failing key is marked
            # rather than deleted, so the owner can see why it stopped working.
            sa.Column('is_valid', sa.Boolean(), nullable=False, server_default=sa.text('true')),
            sa.Column('last_used_at', sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column('created_at', sa.TIMESTAMP(timezone=True),
                      server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
            sa.Column('updated_at', sa.TIMESTAMP(timezone=True),
                      server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
            sa.UniqueConstraint('owner_id', 'provider',
                                name='user_provider_keys_owner_id_provider_key'),
        )

    if 'idx_keys_owner_provider' not in _existing_indexes(TABLE):
        op.create_index('idx_keys_owner_provider', TABLE, ['owner_id', 'provider'])


def downgrade():
    # Drops the ciphertext with the table. There is no soft delete here by design.
    if _has_table(TABLE):
        op.drop_table(TABLE)
