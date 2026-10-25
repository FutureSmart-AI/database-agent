"""No provider calls: a table the router declines by shape is a direct response, not a 500.

route_query ends the graph before any LLM call for an empty, single-scalar or
single-row table, and sets no response. generate_graph_from_csv used to treat
an END without a response as a chart and crash on graph_data=None — the Chart
API answered 500 "'NoneType' object has no attribute 'get'" for every such CSV
(13 of 17 Document Intelligence chart calls in the 30 days to 2026-10-25).
"""
import asyncio
import os
import tempfile
import unittest

for name, value in {
    "LANGCHAIN_TRACING_V2": "false", "LANGSMITH_TRACING": "false", "OTEL_EXPORTER_ENDPOINT": "",
}.items():
    os.environ[name] = value
# chart_agent.graph imports the metadata-store session module, which only builds
# its URL at import time — nothing here connects to it.
for name, value in {
    "POSTGRES_USER": "u", "POSTGRES_PASSWORD": "p", "POSTGRES_HOST": "localhost",
    "POSTGRES_PORT": "5432", "POSTGRES_DB_NAME": "unused",
}.items():
    os.environ.setdefault(name, value)

from chart_agent.graph import NO_CHART_FOR_DATA_SHAPE, generate_graph_from_csv


def _csv(text):
    handle = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8")
    handle.write(text)
    handle.close()
    return handle.name


class NoChartShapeTests(unittest.TestCase):
    def _generate(self, text):
        path = _csv(text)
        try:
            return asyncio.run(generate_graph_from_csv(csv_path=path, question="chart this"))
        finally:
            os.remove(path)

    def test_single_row_table_is_a_direct_response(self):
        result = self._generate("company,travel_allowance_per_day\nNorthwind,85\n")
        self.assertEqual(result["is_direct_response"], True)
        self.assertEqual(result["response"], NO_CHART_FOR_DATA_SHAPE)

    def test_single_scalar_is_a_direct_response(self):
        result = self._generate("total\n42\n")
        self.assertEqual(result["is_direct_response"], True)

    def test_empty_table_is_a_direct_response(self):
        result = self._generate("company,amount\n")
        self.assertEqual(result["is_direct_response"], True)


if __name__ == "__main__":
    unittest.main()
