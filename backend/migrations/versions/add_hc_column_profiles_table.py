"""Add hc_column_profiles table

Revision ID: add_hc_column_profiles
Revises: add_show_sql_and_result_flags
Create Date: 2026-06-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'add_hc_column_profiles'
down_revision = 'add_show_sql_and_result_flags'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'hc_column_profiles',
        sa.Column('chatbot_id', sa.String(), nullable=False),
        sa.Column('agent_id', sa.String(), nullable=True),
        sa.Column('table_name', sa.String(), nullable=False),
        sa.Column('column_profiles', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('profiled_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('chatbot_id', 'table_name'),
    )
    op.create_index('ix_hc_column_profiles_chatbot_id', 'hc_column_profiles', ['chatbot_id'])
    op.create_index('ix_hc_column_profiles_agent_id', 'hc_column_profiles', ['agent_id'])
    op.create_index('ix_hc_column_profiles_table_name', 'hc_column_profiles', ['table_name'])


def downgrade():
    op.drop_index('ix_hc_column_profiles_table_name', 'hc_column_profiles')
    op.drop_index('ix_hc_column_profiles_agent_id', 'hc_column_profiles')
    op.drop_index('ix_hc_column_profiles_chatbot_id', 'hc_column_profiles')
    op.drop_table('hc_column_profiles')
