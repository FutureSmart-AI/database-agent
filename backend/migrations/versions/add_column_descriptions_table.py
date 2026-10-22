"""Add column_descriptions table

Revision ID: d4e7f8a9b2c1
Revises: c65998cce9d1
Create Date: 2025-11-02 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'd4e7f8a9b2c1'
down_revision = 'c65998cce9d1'
branch_labels = None
depends_on = None


def upgrade():
    # Create column_descriptions table
    op.create_table(
        'column_descriptions',
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('chatbot_id', sa.String(), nullable=False),
        sa.Column('table_name', sa.String(), nullable=False),
        sa.Column('column_descriptions', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('user_id', 'chatbot_id', 'table_name')
    )

    # Create indexes
    op.create_index('ix_column_descriptions_user_id', 'column_descriptions', ['user_id'])
    op.create_index('ix_column_descriptions_chatbot_id', 'column_descriptions', ['chatbot_id'])
    op.create_index('ix_column_descriptions_table_name', 'column_descriptions', ['table_name'])


def downgrade():
    # Drop indexes
    op.drop_index('ix_column_descriptions_table_name', 'column_descriptions')
    op.drop_index('ix_column_descriptions_chatbot_id', 'column_descriptions')
    op.drop_index('ix_column_descriptions_user_id', 'column_descriptions')

    # Drop table
    op.drop_table('column_descriptions')

