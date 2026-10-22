from logging.config import fileConfig
import os
from dotenv import load_dotenv
from sqlalchemy import engine_from_config
from sqlalchemy import pool
from sqlmodel import SQLModel
from alembic import context
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from models.sql_models import SQLModel, ChatbotDetails, ChatbotInvitations, ChatSessions, ChatLogs, TableDescription, ColumnDescription, FewShotExamples, Users, ApiKeys, ChatbotNodeConfig, HCColumnProfiles

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

from runtime_config import load_environment, metadata_url
load_environment()

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

from models.sql_models import SQLModel
# Import all models to ensure Alembic can detect changes
from models.sql_models import ChatbotDetails, ChatbotInvitations, ChatSessions, ChatLogs, TableDescription, ColumnDescription, FewShotExamples, Users, ApiKeys, ChatbotNodeConfig, HCColumnProfiles
# Batch Query Reports tables live in their own package rather than models/sql_models.py, so
# they need their own import here — without it autogenerate would see them as missing and
# propose dropping them.
from batch_query_reports.pydantic_model_db import (
    Report, ReportSettings, ReportRun, ReportRunGroup, ReportRunQuery, ReportRunResult,
)

target_metadata = SQLModel.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.

config.set_main_option(
    "sqlalchemy.url",
    metadata_url("psycopg2").render_as_string(hide_password=False).replace("%", "%%"),
)

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    supplied = config.attributes.get("connection")
    if supplied is not None:
        context.configure(connection=supplied, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
        return
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
