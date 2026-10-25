"""Add agent_id column to all tables with chatbot_id

Revision ID: add_agent_id_column
Revises: c65998cce9d1
Create Date: 2025-11-03 00:00:00.000000

This migration adds agent_id column to all tables that currently use chatbot_id.
The agent_id column will be populated with the same values as chatbot_id for backward compatibility.
Both columns will be maintained to ensure old endpoints continue to work.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_agent_id_column'
down_revision = 'd4e7f8a9b2c1'  # Depends on column_descriptions table
branch_labels = None
depends_on = None


def upgrade():
    """
    Add agent_id column to all tables with chatbot_id and copy data.
    """
    
    # List of tables that have chatbot_id column
    tables_with_chatbot_id = [
        'chatbot_connection',
        'chat_sessions',
        'few_shot_examples',
        'api_keys',
        'table_descriptions',
        'column_descriptions',
        'chatbot_details',
        'chatbot_invitations',
        'chatbot_node_config',
        'nl2sql_logs'
    ]
    
    # Add agent_id column to each table
    for table_name in tables_with_chatbot_id:
        # Add agent_id column (nullable initially to allow data migration)
        op.add_column(table_name, sa.Column('agent_id', sa.String(), nullable=True))
        
        # Copy data from chatbot_id to agent_id
        op.execute(f"UPDATE {table_name} SET agent_id = chatbot_id")
        
        # Create index on agent_id for better query performance
        op.create_index(f'ix_{table_name}_agent_id', table_name, ['agent_id'])
    
    # Note: We keep chatbot_id columns for backward compatibility
    # Both chatbot_id and agent_id will coexist in the database


def downgrade():
    """
    Remove agent_id column from all tables.
    """
    
    tables_with_agent_id = [
        'chatbot_connection',
        'chat_sessions',
        'few_shot_examples',
        'api_keys',
        'table_descriptions',
        'column_descriptions',
        'chatbot_details',
        'chatbot_invitations',
        'chatbot_node_config',
        'nl2sql_logs'
    ]
    
    # Remove agent_id column and its index from each table
    for table_name in tables_with_agent_id:
        # Drop index first
        op.drop_index(f'ix_{table_name}_agent_id', table_name)
        
        # Drop column
        op.drop_column(table_name, 'agent_id')

