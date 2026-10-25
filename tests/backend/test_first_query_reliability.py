"""No provider/DB calls: a refusal is not replayed, and a corrected chart type is re-mapped once."""
import asyncio
import os
import types
import unittest
from unittest.mock import AsyncMock, patch

for name, value in {
    "POSTGRES_USER": "unused", "POSTGRES_PASSWORD": "unused",
    "POSTGRES_HOST": "127.0.0.1", "POSTGRES_PORT": "5432", "POSTGRES_DB_NAME": "unused",
    "LANGCHAIN_TRACING_V2": "false", "LANGSMITH_TRACING": "false", "OTEL_EXPORTER_ENDPOINT": "",
}.items():
    os.environ[name] = value

import pandas as pd

from agent.db_utils.session_db_utils import chat_log_history
from chart_agent import node as chart_node
from chart_agent.graph import create_graph_agent_graph


def turn(query, response, answered):
    return types.SimpleNamespace(user_query=query, gpt_response=response, is_answered=answered)


class HistoryTests(unittest.TestCase):
    def test_refused_turn_keeps_the_question_but_not_the_refusal(self):
        rows = [
            turn("Who are our top five customers by total spend?",
                 "I can't determine this from the available tables: ...", False),
            turn("Only show the top two.", None, None),
        ]
        self.assertEqual(chat_log_history(rows), [
            {"role": "user", "content": "Who are our top five customers by total spend?"},
            {"role": "user", "content": "Only show the top two."},
        ])

    def test_answered_and_unrecorded_turns_keep_their_replies(self):
        rows = [turn("q1", "a1", True), turn("q2", "a2", None)]
        self.assertEqual([m["role"] for m in chat_log_history(rows)],
                         ["user", "assistant", "user", "assistant"])


DF = pd.DataFrame({"id": [7, 3], "first_name": ["Priya", "Arjun"],
                   "last_name": ["Raman", "Mehta"], "total_spend": [11984.2, 9210.75]})


def state(chart, measures, labels):
    return {"processed_dataframe": DF, "suggested_chart_type": chart, "allowed_graphs": None,
            "graph_mapping_spec": {"chart_type": chart, "field_mappings": [],
                                   "measure_columns": measures, "label_columns": labels}}


class ValidationTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(chart_node, "_trace_chart_validation", AsyncMock())
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_named_measure_keeps_bar_chart_and_its_mapping(self):
        out = asyncio.run(chart_node.validate_chart_type_node(
            state("Bar Chart", ["total_spend"], ["first_name", "last_name"])))
        self.assertEqual(out["suggested_chart_type"], "Bar Chart")
        self.assertIsNotNone(out["graph_mapping_spec"])
        self.assertTrue(out["chart_type_checked"])

    def test_correction_clears_the_mapping_once(self):
        first = asyncio.run(chart_node.validate_chart_type_node(
            state("Bar Chart", ["id", "total_spend"], ["first_name"])))
        self.assertEqual(first["chart_type"], "Stacked Bar Chart")
        self.assertIsNone(first["graph_mapping_spec"])
        remapped = {**first, "graph_mapping_spec": {"chart_type": "Stacked Bar Chart", "field_mappings": []}}
        second = asyncio.run(chart_node.validate_chart_type_node(remapped))
        self.assertIs(second, remapped)

    def test_graph_routes_mapping_through_validation(self):
        graph = create_graph_agent_graph().get_graph()
        edges = {(e.source, e.target) for e in graph.edges}
        self.assertIn(("invoke_pandas_agent", "generate_mapping"), edges)
        self.assertIn(("generate_mapping", "validate_chart_type"), edges)
        self.assertIn(("validate_chart_type", "assemble_graph"), edges)
        self.assertIn(("validate_chart_type", "generate_mapping"), edges)


if __name__ == "__main__":
    unittest.main()
