from alembic import op
import sqlalchemy as sa

revision = 'add_is_answered_to_nl2sql_logs'
down_revision = 'add_hc_column_profiles'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('nl2sql_logs', sa.Column('is_answered', sa.Boolean(), nullable=True))


def downgrade():
    op.drop_column('nl2sql_logs', 'is_answered')
