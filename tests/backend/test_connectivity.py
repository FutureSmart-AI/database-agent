"""Installation connectivity regression caught by the real staging wizard."""
import unittest
from unittest.mock import patch
from database_connection.utils.common_utils import validate_database_request
from agent.db_utils.table_description_db_utils import get_db_connection


class PostgreSQLPortTests(unittest.TestCase):
    def test_standard_and_mapped_postgresql_ports_reach_connection_testing(self):
        for port in (5432, 5433, 15432):
            with self.subTest(port=port):
                self.assertEqual(validate_database_request("postgresql", "isolated-source", "sample_sales", port), (True, ""))

    def test_invalid_tcp_ports_are_rejected(self):
        for port in (-1, 0, 65536, True, "5433"):
            with self.subTest(port=port):
                valid, message = validate_database_request("postgresql", "isolated-source", "sample_sales", port)
                self.assertFalse(valid)
                self.assertTrue(message.startswith("PORT_OR_NETWORK:"))

    def test_existing_other_engine_port_rules_remain(self):
        self.assertTrue(validate_database_request("mysql", "source", "sales", 3306)[0])
        self.assertFalse(validate_database_request("mysql", "source", "sales", 3307)[0])
        self.assertTrue(validate_database_request("sqlite", "local", "", 0)[0])
        self.assertFalse(validate_database_request("sqlite", "local", "", 5432)[0])

    def test_sql_execution_connection_uses_the_configured_postgresql_port(self):
        details = dict(db_engine="postgresql", db_host="isolated-source", db_name="sample_sales",
                       db_user="fixture-reader", db_password="fixture-only", db_port=5433)
        with patch("agent.db_utils.table_description_db_utils.psycopg2.connect") as connect:
            get_db_connection({"db_details": details})
            self.assertEqual(connect.call_args.kwargs["port"], 5433)
            self.assertEqual(connect.call_args.kwargs["host"], "isolated-source")

    def test_legacy_postgresql_details_keep_the_standard_port_default(self):
        details = dict(db_engine="postgresql", db_host="isolated-source", db_name="sample_sales",
                       db_user="fixture-reader", db_password="fixture-only")
        with patch("agent.db_utils.table_description_db_utils.psycopg2.connect") as connect:
            get_db_connection({"db_details": details})
            self.assertEqual(connect.call_args.kwargs["port"], 5432)


if __name__ == "__main__":
    unittest.main()
