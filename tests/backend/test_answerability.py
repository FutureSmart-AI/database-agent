"""No provider/DB calls: schema support, valid zero, denied reads and failed queries."""
import os
import unittest
from unittest.mock import AsyncMock, Mock, patch

for name, value in {
    "POSTGRES_USER": "unused", "POSTGRES_PASSWORD": "unused",
    "POSTGRES_HOST": "127.0.0.1", "POSTGRES_PORT": "5432", "POSTGRES_DB_NAME": "unused",
    "LANGCHAIN_TRACING_V2": "false", "LANGSMITH_TRACING": "false", "OTEL_EXPORTER_ENDPOINT": "",
}.items():
    os.environ[name] = value

from agent.utils.answerability import apply_sql_decision, failure_response
from agent.nodes import sql_exec, final_answer, cross_db_merge
from agent.utils import table_access


class DecisionTests(unittest.TestCase):
    def test_missing_schema_discards_surrogate_sql_and_stale_rows(self):
        state = {"db_result": [(12,)], "db_columns": ["count"], "sql_error": "old"}
        sql = apply_sql_decision(state, {"answerable": False, "generated_query": "SELECT count(*) FROM action_log",
                                         "reason": "No schema represents the requested business metric."})
        self.assertEqual(sql, "")
        self.assertEqual(state["db_result"], [])
        self.assertIsNone(state["sql_error"])
        self.assertIn("available tables", failure_response(state))

    def test_correct_count_query_is_not_rejected_based_on_its_result(self):
        for value in (0, 2, 4):
            with self.subTest(value=value):
                state = {"db_result": [(value,)], "answerability_error": "stale"}
                self.assertEqual(apply_sql_decision(state, {"answerable": True, "generated_query": "SELECT COUNT(*) FROM legitimate_source"}),
                                 "SELECT COUNT(*) FROM legitimate_source")
                self.assertIsNone(failure_response(state))

    def test_missing_or_malformed_support_decision_cannot_approve_raw_sql(self):
        for output in ({"generated_query": "SELECT 0"}, {"answerable": "true", "generated_query": "SELECT 0"},
                       {"answerable": True, "generated_query": ""}):
            with self.subTest(output=output), self.assertRaises(ValueError):
                apply_sql_decision({}, output)


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_unsupported_sql_never_reaches_database_or_final_answer_model(self):
        state = {"answerability_error": "Unsupported schema", "sql_query": "SELECT 0", "db_result": [(0,)]}
        with patch.object(sql_exec, "try_exec_sql", side_effect=AssertionError("must not execute")), \
             patch.object(final_answer, "get_agent_node_config", side_effect=AssertionError("must not invoke model")):
            state = await sql_exec.node_sql_exec(state)
            state = await final_answer.node_final_answer(state)
        self.assertIs(state["is_answered"], False)
        self.assertEqual(state["sql_query"], "")
        self.assertEqual(state["db_result"], [])

    async def test_existing_table_guard_still_blocks_before_execution(self):
        state = {"sql_query": "SELECT count(*) FROM product_reviews", "runtime_db_details": {"db_engine": "postgresql"}}
        with patch.object(table_access, "get_table_visibility", AsyncMock(return_value=(["orders"], ["product_reviews"]))), \
             patch.object(sql_exec, "try_exec_sql", side_effect=AssertionError("denied query executed")):
            state = await sql_exec.node_sql_exec(state)
        self.assertEqual(state["access_denied_tables"], ["product_reviews"])
        state = await final_answer.node_final_answer(state)
        self.assertIs(state["is_answered"], False)
        self.assertIn("restricted", state["response"])
        self.assertEqual(state["db_result"], [])

    async def test_valid_zero_reaches_database_and_remains_answerable(self):
        state = {"sql_query": "SELECT count(*) FROM product_reviews WHERE rating=5", "runtime_db_details": {"db_engine": "postgresql"}}
        execute = Mock(return_value=(True, (["count"], [(0,)]), None))
        tracker = Mock(record_event=AsyncMock())
        with patch.object(table_access, "get_table_visibility", AsyncMock(return_value=(["product_reviews"], []))), \
             patch.object(sql_exec, "try_exec_sql", execute), patch.object(sql_exec, "get_usage_tracker", return_value=tracker):
            state = await sql_exec.node_sql_exec(state)
        execute.assert_called_once()
        self.assertEqual(state["db_result"], [(0,)])
        self.assertIsNone(failure_response(state))

    async def test_malformed_sql_and_unavailable_connection_do_not_become_zero(self):
        for error in ('syntax error at "FROM"', "could not connect to source"):
            with self.subTest(error=error):
                state = {"sql_query": "SELECT count(*) FROM orders", "runtime_db_details": {"db_engine": "postgresql"}}
                with patch.object(table_access, "get_table_visibility", AsyncMock(return_value=(["orders"], []))), \
                     patch.object(sql_exec, "try_exec_sql", return_value=(False, None, error)), \
                     patch.object(sql_exec, "get_usage_tracker", return_value=Mock(record_event=AsyncMock())):
                    state = await sql_exec.node_sql_exec(state)
                state = await final_answer.node_final_answer(state)
                self.assertIs(state["is_answered"], False)
                self.assertIn("query failed", state["response"])
                self.assertEqual(state["db_result"], [])

    async def test_all_cross_db_subquestions_unsupported_remain_unavailable(self):
        state = {"cross_db_results": [{"db_id": "one", "rows": [], "answerability_error": "Missing metric"},
                                      {"db_id": "two", "rows": [], "answerability_error": "Missing metric"}]}
        state = await cross_db_merge.node_cross_db_merge(state)
        state = await final_answer.node_final_answer(state)
        self.assertIs(state["is_answered"], False)
        self.assertIn("available tables", state["response"])
        self.assertEqual(state["db_result"], [])

    async def test_mixed_required_sources_retain_combination_error_not_global_absence(self):
        for count in (0, 2):
            with self.subTest(count=count):
                state = {"cross_db_results": [
                    {"db_id": "one", "rows": [(count,)], "columns": ["count"]},
                    {"db_id": "two", "rows": [], "answerability_error": "Missing metric"},
                ]}
                state = await cross_db_merge.node_cross_db_merge(state)
                self.assertIsNone(state["answerability_error"])
                self.assertIn("not all databases returned usable results", state["sql_error"])
                state = await final_answer.node_final_answer(state)
                self.assertIs(state["is_answered"], False)
                self.assertIn("query failed", state["response"])
                self.assertNotIn("don't contain data", state["response"])


if __name__ == "__main__":
    unittest.main()
