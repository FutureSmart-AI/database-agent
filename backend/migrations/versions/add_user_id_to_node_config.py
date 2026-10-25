"""Add user_id column to chatbot_node_config

Revision ID: add_user_id_to_node_config
Revises: add_description_provenance
Create Date: 2026-07-02 00:00:00.000000

Records the acting dashboard user on node-config upserts. Nullable: internal /
API-key (master) calls leave it NULL, only session (dashboard) writes stamp it.
"""
from alembic import op
import sqlalchemy as sa

revision = 'add_user_id_to_node_config'
down_revision = 'add_description_provenance'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('chatbot_node_config', sa.Column('user_id', sa.String(), nullable=True))
    op.create_index('ix_chatbot_node_config_user_id', 'chatbot_node_config', ['user_id'])


def downgrade():
    op.drop_index('ix_chatbot_node_config_user_id', 'chatbot_node_config')
    op.drop_column('chatbot_node_config', 'user_id')
