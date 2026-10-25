from alembic import op
import sqlalchemy as sa

revision = 'add_show_sql_and_result_flags'
down_revision = 'add_agent_params_columns'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('chatbot_details', sa.Column('show_sql_query', sa.Boolean(), nullable=True, server_default=sa.true()))
    op.add_column('chatbot_details', sa.Column('show_db_result', sa.Boolean(), nullable=True, server_default=sa.true()))


def downgrade():
    op.drop_column('chatbot_details', 'show_db_result')
    op.drop_column('chatbot_details', 'show_sql_query')
