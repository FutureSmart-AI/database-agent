"""Add description provenance fields to chatbot_connection"""
from alembic import op
import sqlalchemy as sa

revision = 'add_description_provenance'
down_revision = 'multi_db_support'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('chatbot_connection', sa.Column('description_source', sa.String(), nullable=True))
    op.add_column('chatbot_connection', sa.Column('description_updated_at', sa.DateTime(), nullable=True))
    # Existing rows that already have a description are treated as manually set.
    op.execute("""
        UPDATE chatbot_connection
        SET description_source = 'manual',
            description_updated_at = COALESCE(updated_at, now())
        WHERE description IS NOT NULL AND description <> ''
    """)


def downgrade():
    op.drop_column('chatbot_connection', 'description_updated_at')
    op.drop_column('chatbot_connection', 'description_source')
