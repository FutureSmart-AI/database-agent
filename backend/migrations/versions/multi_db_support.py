"""Multi-DB support: db_id on connections + per-DB metadata + description jobs

Revision ID: multi_db_support
Revises: add_is_answered_to_nl2sql_logs
Create Date: 2026-06-28 00:00:00.000000

Makes an agent able to own many source databases:
  * chatbot_connection becomes multi-row, keyed by a new db_id (DB_<8hex>).
  * db_id is added to table_descriptions / column_descriptions /
    hc_column_profiles / few_shot_examples and folded into their primary keys.
  * Existing rows are back-filled to each agent's primary db_id.
  * description_generation_jobs is created for the async auto-generate flow.

PostgreSQL-specific (the deployment target). The Qdrant payload back-fill is a
separate idempotent script (see docs/multi-db-spec.md §3.5 step 5).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'multi_db_support'
down_revision = 'add_is_answered_to_nl2sql_logs'
branch_labels = None
depends_on = None


# Deterministic-ish unique db_id generator for existing rows.
_NEW_DB_ID = "'DB_' || upper(substr(md5(random()::text || coalesce(chatbot_id, agent_id, '')), 1, 8))"


def upgrade():
    # ── 1. chatbot_connection: add multi-DB columns ───────────────────────────
    op.add_column('chatbot_connection', sa.Column('db_id', sa.String(), nullable=True))
    op.add_column('chatbot_connection', sa.Column('description', sa.Text(), nullable=True))
    op.add_column('chatbot_connection', sa.Column('is_active', sa.Boolean(), nullable=True))
    op.add_column('chatbot_connection', sa.Column('status', sa.String(), nullable=True))
    op.add_column('chatbot_connection', sa.Column('table_count', sa.Integer(), nullable=True))
    op.add_column('chatbot_connection', sa.Column('created_at', sa.DateTime(), nullable=True))
    op.add_column('chatbot_connection', sa.Column('updated_at', sa.DateTime(), nullable=True))

    # Back-fill each existing connection with a db_id (one row per agent today).
    # No primary flag: the pipeline treats the oldest active DB as primary.
    op.execute(f"""
        UPDATE chatbot_connection
        SET db_id = {_NEW_DB_ID},
            is_active = TRUE,
            status = 'connected',
            created_at = COALESCE(created_at, now()),
            updated_at = COALESCE(updated_at, now())
        WHERE db_id IS NULL
    """)
    op.alter_column('chatbot_connection', 'db_id', nullable=False)

    # Swap primary key chatbot_id -> db_id.
    op.drop_constraint('chatbot_connection_pkey', 'chatbot_connection', type_='primary')
    op.alter_column('chatbot_connection', 'chatbot_id', nullable=True)
    op.create_primary_key('chatbot_connection_pkey', 'chatbot_connection', ['db_id'])
    op.create_index('ix_chatbot_connection_db_id', 'chatbot_connection', ['db_id'])

    # ── 2. per-DB metadata tables: add db_id, back-fill, extend PKs ────────────
    _add_db_id_and_repk(
        table='table_descriptions',
        old_pk_cols=['chatbot_id'],
        new_pk_cols=['chatbot_id', 'db_id'],
        pkey_name='table_descriptions_pkey',
    )
    _add_db_id_and_repk(
        table='column_descriptions',
        old_pk_cols=['chatbot_id', 'table_name'],
        new_pk_cols=['chatbot_id', 'db_id', 'table_name'],
        pkey_name='column_descriptions_pkey',
    )
    _add_db_id_and_repk(
        table='hc_column_profiles',
        old_pk_cols=['chatbot_id', 'table_name'],
        new_pk_cols=['chatbot_id', 'db_id', 'table_name'],
        pkey_name='hc_column_profiles_pkey',
    )
    _add_db_id_and_repk(
        table='few_shot_examples',
        old_pk_cols=['chatbot_id'],
        new_pk_cols=['chatbot_id', 'db_id'],
        pkey_name='few_shot_examples_pkey',
    )

    # ── 3. description_generation_jobs ─────────────────────────────────────────
    op.create_table(
        'description_generation_jobs',
        sa.Column('job_id', sa.String(), nullable=False),
        sa.Column('agent_id', sa.String(), nullable=True),
        sa.Column('db_id', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('job_id'),
    )
    op.create_index('ix_description_generation_jobs_agent_id', 'description_generation_jobs', ['agent_id'])
    op.create_index('ix_description_generation_jobs_db_id', 'description_generation_jobs', ['db_id'])


def _add_db_id_and_repk(table, old_pk_cols, new_pk_cols, pkey_name):
    """Add a db_id column to a per-agent metadata table and re-key it per DB."""
    op.add_column(table, sa.Column('db_id', sa.String(), nullable=True))

    # Back-fill db_id from the agent's connection. At migration time each agent has exactly
    # one connection (chatbot_id was a unique PK), so this is unambiguous. Match on agent_id
    # OR chatbot_id (legacy rows may have only one populated) so a metadata row always lands
    # on the SAME db_id the pipeline later resolves as primary — never an orphan id.
    op.execute(f"""
        UPDATE {table} t
        SET db_id = c.db_id
        FROM chatbot_connection c
        WHERE (
                (t.agent_id IS NOT NULL AND c.agent_id = t.agent_id)
             OR (t.chatbot_id IS NOT NULL AND c.chatbot_id = t.chatbot_id)
          )
          AND t.db_id IS NULL
    """)
    # Last-resort fallback ONLY for metadata whose agent has no connection at all
    # (truly orphaned). These rows can never be queried by the pipeline anyway.
    op.execute(f"UPDATE {table} SET db_id = chatbot_id WHERE db_id IS NULL")
    op.alter_column(table, 'db_id', nullable=False)

    op.drop_constraint(pkey_name, table, type_='primary')
    op.create_primary_key(pkey_name, table, new_pk_cols)
    op.create_index(f'ix_{table}_db_id', table, ['db_id'])


def downgrade():
    # description_generation_jobs
    op.drop_index('ix_description_generation_jobs_db_id', 'description_generation_jobs')
    op.drop_index('ix_description_generation_jobs_agent_id', 'description_generation_jobs')
    op.drop_table('description_generation_jobs')

    # per-DB metadata tables: restore old PKs, drop db_id
    for table, old_pk_cols, pkey_name in [
        ('few_shot_examples', ['chatbot_id'], 'few_shot_examples_pkey'),
        ('hc_column_profiles', ['chatbot_id', 'table_name'], 'hc_column_profiles_pkey'),
        ('column_descriptions', ['chatbot_id', 'table_name'], 'column_descriptions_pkey'),
        ('table_descriptions', ['chatbot_id'], 'table_descriptions_pkey'),
    ]:
        op.drop_index(f'ix_{table}_db_id', table)
        op.drop_constraint(pkey_name, table, type_='primary')
        op.create_primary_key(pkey_name, table, old_pk_cols)
        op.drop_column(table, 'db_id')

    # chatbot_connection: restore chatbot_id PK, drop new columns
    op.drop_index('ix_chatbot_connection_db_id', 'chatbot_connection')
    op.drop_constraint('chatbot_connection_pkey', 'chatbot_connection', type_='primary')
    op.alter_column('chatbot_connection', 'chatbot_id', nullable=False)
    op.create_primary_key('chatbot_connection_pkey', 'chatbot_connection', ['chatbot_id'])
    for col in ['updated_at', 'created_at', 'table_count', 'status',
                'is_active', 'description', 'db_id']:
        op.drop_column('chatbot_connection', col)
