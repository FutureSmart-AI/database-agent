"""No provider calls: an identifier column is not a chart series (DA-CHART-002)."""
import os
import unittest

for name, value in {
    "LANGCHAIN_TRACING_V2": "false", "LANGSMITH_TRACING": "false", "OTEL_EXPORTER_ENDPOINT": "",
}.items():
    os.environ[name] = value

import pandas as pd

from chart_agent.utils.graph_assembler import (
    assemble_graph_data,
    combine_label_columns,
    infer_correct_chart_type,
)

# The exact result shape from the hosted landing-page audit.
TOP_CUSTOMERS = pd.DataFrame({
    "id": [7, 3, 11],
    "first_name": ["Priya", "Arjun", "Sneha"],
    "last_name": ["Raman", "Mehta", "Kulkarni"],
    "total_spend": [11984.2, 9210.75, 7488.9],
})
BAR_MAPPING = [
    {"graph_field": "category", "dataframe_column": "first_name", "description": "customer"},
    {"graph_field": "value", "dataframe_column": "total_spend", "description": "spend"},
]


class ChartTypeTests(unittest.TestCase):
    def test_without_named_measures_the_id_still_counts_as_a_series(self):
        # The pre-fix behaviour, kept as the fallback when no measures are named.
        chart, reason = infer_correct_chart_type(TOP_CUSTOMERS, "Bar Chart")
        self.assertEqual(chart, "Stacked Bar Chart")
        self.assertIn("id", reason)

    def test_named_measure_keeps_the_bar_chart(self):
        chart, reason = infer_correct_chart_type(
            TOP_CUSTOMERS, "Bar Chart", None, ["total_spend"], ["first_name", "last_name"]
        )
        self.assertEqual((chart, reason), ("Bar Chart", None))

    def test_two_real_measures_still_become_a_stacked_chart(self):
        df = pd.DataFrame({"region": ["N", "S"], "online": [4.0, 5.0], "store": [2.0, 1.0]})
        chart, _ = infer_correct_chart_type(df, "Bar Chart", None, ["online", "store"], ["region"])
        self.assertEqual(chart, "Stacked Bar Chart")

    def test_split_name_is_one_dimension_for_a_stacked_request(self):
        chart, _ = infer_correct_chart_type(
            TOP_CUSTOMERS, "Stacked Bar Chart", None, ["total_spend"], ["first_name", "last_name"]
        )
        self.assertEqual(chart, "Bar Chart")

    def test_unknown_measure_names_fall_back_to_numeric_columns(self):
        chart, _ = infer_correct_chart_type(TOP_CUSTOMERS, "Bar Chart", None, ["spend"], None)
        self.assertEqual(chart, "Stacked Bar Chart")


class LabelTests(unittest.TestCase):
    def test_full_name_becomes_the_bar_label(self):
        df, mappings = combine_label_columns(TOP_CUSTOMERS, BAR_MAPPING, ["first_name", "last_name"])
        graph = assemble_graph_data(df, "Bar Chart", mappings, {"title": "Top customers"}, verbose=False)
        self.assertEqual(
            [item["category"] for item in graph["data"]],
            ["Priya Raman", "Arjun Mehta", "Sneha Kulkarni"],
        )
        self.assertEqual([item["value"] for item in graph["data"]], [11984.2, 9210.75, 7488.9])

    def test_a_mapping_of_the_second_name_part_is_dropped(self):
        stacked = BAR_MAPPING + [
            {"graph_field": "segment_category", "dataframe_column": "last_name", "description": "x"}
        ]
        _, mappings = combine_label_columns(TOP_CUSTOMERS, stacked, ["first_name", "last_name"])
        self.assertNotIn("last_name", [m["dataframe_column"] for m in mappings])

    def test_single_label_column_is_unchanged(self):
        df, mappings = combine_label_columns(TOP_CUSTOMERS, BAR_MAPPING, ["first_name"])
        self.assertIs(df, TOP_CUSTOMERS)
        self.assertIs(mappings, BAR_MAPPING)


if __name__ == "__main__":
    unittest.main()
