"""No DB calls: every source connection uses the stored port (DA-PROFILE-PORT-001)."""
import asyncio
import os
import unittest
from unittest.mock import MagicMock, patch

for name, value in {
    "POSTGRES_USER": "unused", "POSTGRES_PASSWORD": "unused",
    "POSTGRES_HOST": "127.0.0.1", "POSTGRES_PORT": "5432", "POSTGRES_DB_NAME": "unused",
    "LANGCHAIN_TRACING_V2": "false", "LANGSMITH_TRACING": "false", "OTEL_EXPORTER_ENDPOINT": "",
}.items():
    os.environ[name] = value

from database_connection import source_connection
from knowledge.db_utils import database_db_utils
from agent.db_utils import table_description_db_utils as agent_tables
from database_connection.db_utils import table_description_db_utils as connection_tables

PG = {"db_engine": "postgresql", "db_host": "10.0.0.5", "db_user": "reader",
      "db_password": "synthetic", "db_name": "shop_demo", "db_port": 5434}
MY = {**PG, "db_engine": "mysql", "db_port": "3307"}


def fake_connection(tables):
    cursor = MagicMock()
    cursor.fetchall.return_value = [(t,) for t in tables]
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    return conn


class PortTests(unittest.TestCase):
    def test_stored_port_wins_and_default_fills_a_missing_one(self):
        self.assertEqual(source_connection.source_port(PG), 5434)
        self.assertEqual(source_connection.source_port(MY), 3307)
        self.assertEqual(source_connection.source_port({**PG, "db_port": None}), 5432)
        self.assertEqual(source_connection.source_port({**MY, "db_port": ""}), 3306)

    def test_every_listing_path_connects_on_the_stored_port(self):
        with patch.object(source_connection.psycopg2, "connect", return_value=fake_connection(["orders"])) as pg, \
             patch.object(source_connection.pymysql, "connect", return_value=fake_connection(["orders"])) as my:
            self.assertEqual(asyncio.run(database_db_utils.get_all_tables(PG)), ["orders"])
            asyncio.run(database_db_utils.get_table_columns(PG, "orders"))
            agent_tables.get_db_connection({"db_details": PG})
            connection_tables.get_db_connection({"db_details": PG})
            asyncio.run(database_db_utils.get_all_tables(MY))
            asyncio.run(database_db_utils.get_table_columns(MY, "orders"))
            agent_tables.get_db_connection({"db_details": MY})
            connection_tables.get_db_connection({"db_details": MY})
        self.assertEqual([c.kwargs["port"] for c in pg.call_args_list], [5434] * 4)
        self.assertEqual([c.kwargs["port"] for c in my.call_args_list], [3307] * 4)
        self.assertEqual({c.kwargs["dbname"] for c in pg.call_args_list}, {"shop_demo"})

    def test_unknown_engine_is_refused(self):
        with self.assertRaises(ValueError):
            source_connection.open_source_connection({**PG, "db_engine": "oracle"})


if __name__ == "__main__":
    unittest.main()
