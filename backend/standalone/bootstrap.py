"""Initialize an EMPTY metadata database, then apply normal Alembic upgrades.

Historical Alembic base is empty (it assumed a preexisting schema). This frozen
baseline is deliberately stamped at its matching revision, never at a moving head.
Existing databases without Alembic history are rejected rather than stamped.
"""
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from runtime_config import ROOT, metadata_url

BASELINE_REVISION = "add_agent_is_demo"


def bootstrap():
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    engine = create_engine(metadata_url("psycopg2"))
    try:
        with engine.begin() as connection:
            # Serialize two bootstrap invocations on this database.
            connection.exec_driver_sql("SELECT pg_advisory_xact_lock(20261020)")
            tables = set(inspect(connection).get_table_names())
            config.attributes["connection"] = connection
            if not tables:
                connection.exec_driver_sql(Path(__file__).with_name("baseline.sql").read_text(encoding="utf-8"))
                command.stamp(config, BASELINE_REVISION)
                print("Created frozen empty-database baseline")
            elif "alembic_version" not in tables:
                raise RuntimeError("Refusing to bootstrap a nonempty, unversioned metadata database")
            command.upgrade(config, "head")
    finally:
        engine.dispose()
    print("Metadata bootstrap/upgrade complete")


if __name__ == "__main__":
    bootstrap()
