"""
Revision ID: c65998cce9d1
Revises: bd5f0e074635
Create Date: 2025-11-01 01:26:09.390335
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c65998cce9d1'
down_revision = 'bd5f0e074635'
branch_labels = None
depends_on = None


def upgrade():
    # Create chatbot_node_config table
    op.create_table(
        'chatbot_node_config',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('chatbot_id', sa.String(), nullable=False),
        sa.Column('node_name', sa.String(), nullable=False),
        sa.Column('provider', sa.String(), nullable=True),
        sa.Column('model', sa.String(), nullable=True),
        sa.Column('temperature', sa.Float(), nullable=True),
        sa.Column('max_tokens', sa.Integer(), nullable=True),
        sa.Column('is_default', sa.Boolean(), nullable=True),
        sa.Column('prompt', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes
    op.create_index('ix_chatbot_node_config_chatbot_id', 'chatbot_node_config', ['chatbot_id'])
    op.create_index('ix_chatbot_node_config_node_name', 'chatbot_node_config', ['node_name'])


def downgrade():
    # Drop indexes
    op.drop_index('ix_chatbot_node_config_node_name', 'chatbot_node_config')
    op.drop_index('ix_chatbot_node_config_chatbot_id', 'chatbot_node_config')

    # Drop table
    op.drop_table('chatbot_node_config')