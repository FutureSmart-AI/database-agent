from alembic import op
import sqlalchemy as sa

revision = 'add_agent_params_columns'
down_revision = 'add_agent_id_column'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('chatbot_details', sa.Column('debug_info', sa.Boolean(), nullable=True))
    op.add_column('chatbot_details', sa.Column('graph_output', sa.Boolean(), nullable=True))
    op.add_column('chatbot_details', sa.Column('allowed_graphs', sa.JSON(), nullable=True))
    op.add_column('chatbot_details', sa.Column('max_query_execution_time', sa.Integer(), nullable=True))
    op.add_column('chatbot_details', sa.Column('enable_query_caching', sa.Boolean(), nullable=True))
    op.add_column('chatbot_details', sa.Column('default_max_tokens', sa.Integer(), nullable=True))


def downgrade():
    op.drop_column('chatbot_details', 'default_max_tokens')
    op.drop_column('chatbot_details', 'enable_query_caching')
    op.drop_column('chatbot_details', 'max_query_execution_time')
    op.drop_column('chatbot_details', 'allowed_graphs')
    op.drop_column('chatbot_details', 'graph_output')
    op.drop_column('chatbot_details', 'debug_info')
