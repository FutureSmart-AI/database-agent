"""Per-answer usage block: latency, tokens and the list-price cost estimate (DA-COST-001)."""
import asyncio
import unittest

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from agent.utils.model_pricing import answer_usage, collect_llm_usage, load_prices, node_cost
from agent.utils.node_metrics import get_node_events, measure_node_calls, record_node_seconds


class ModelPricingTest(unittest.TestCase):
    def test_price_table_is_dated_and_sourced(self):
        prices = load_prices()
        self.assertTrue(prices["version"].startswith("openai-standard-"))
        self.assertIn("developers.openai.com", prices["source"])
        for rate in prices["models"].values():
            self.assertGreaterEqual(rate["input"], 0)

    def test_node_cost_uses_cached_rate_only_for_reported_cached_tokens(self):
        event = {"provider": "openai", "model": "gpt-6.1-sol", "input_tokens": 10_000,
                 "cached_input_tokens": 4_000, "output_tokens": 1_000}
        # 6,000 x $2.00 + 4,000 x $0.10 + 1,000 x $10.00, per million
        self.assertAlmostEqual(node_cost(event), (12_000 + 400 + 10_000) / 1_000_000)
        event.pop("cached_input_tokens")
        self.assertAlmostEqual(node_cost(event), (20_000 + 10_000) / 1_000_000)

    def test_unpriced_model_makes_the_total_incomplete_never_free(self):
        usage = answer_usage([
            {"node_name": "sql_gen", "provider": "openai", "model": "gpt-6-luna",
             "input_tokens": 1000, "output_tokens": 100, "total_tokens": 1100},
            {"node_name": "final_answer", "provider": "anthropic", "model": "some-claude",
             "input_tokens": 500, "output_tokens": 50, "total_tokens": 550},
            {"node_name": "sql_exec", "latency_ms": 12},
        ], 2345.6)
        self.assertEqual(usage["latency_ms"], 2345)
        self.assertFalse(usage["cost_complete"])
        nodes = {n["node"]: n for n in usage["nodes"]}
        self.assertIsNone(nodes["final_answer"]["estimated_cost_usd"])
        self.assertIsNone(nodes["sql_exec"]["estimated_cost_usd"])
        self.assertAlmostEqual(usage["estimated_cost_usd"], (100 + 50) / 1_000_000)
        self.assertEqual(usage["input_tokens"], 1500)
        self.assertEqual(usage["excludes"], ["follow_up_suggestions", "embeddings"])

    def test_recorded_node_events_price_end_to_end(self):
        state = {}
        record_node_seconds(state, "sql_gen", 1.5, provider="openai", model="gpt-6.1-sol",
                            input_tokens=2000, output_tokens=300, total_tokens=2300,
                            cached_input_tokens=1024)
        record_node_seconds(state, "sql_gen", 0.5, provider="openai", model="gpt-6.1-sol",
                            input_tokens=1000, output_tokens=100, total_tokens=1100)
        events = get_node_events(state)
        self.assertEqual(events[0]["cached_input_tokens"], 1024)
        self.assertEqual(events[0]["calls"], 2)
        usage = answer_usage(events, 2000)
        expected = ((3000 - 1024) * 2.0 + 1024 * 0.10 + 400 * 10.0) / 1_000_000
        self.assertAlmostEqual(usage["estimated_cost_usd"], round(expected, 6))
        self.assertTrue(usage["cost_complete"])
        self.assertEqual(usage["nodes"][0]["latency_ms"], 2000)


class PricedFake(GenericFakeChatModel):
    """A real LangChain chat model with a fake transport, reporting as an OpenAI model."""
    priced_as: str = "gpt-6.1-sol"

    def _get_ls_params(self, stop=None, **kwargs):
        params = super()._get_ls_params(stop=stop, **kwargs)
        params.update(ls_provider="openai", ls_model_name=self.priced_as)
        return params


def fake(model, input_tokens, output_tokens, cached=0):
    message = AIMessage(content="ok", usage_metadata={
        "input_tokens": input_tokens, "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens, "input_token_details": {"cache_read": cached}})
    return PricedFake(messages=iter([message]), priced_as=model)


class RunUsageCollectorTest(unittest.IsolatedAsyncioTestCase):
    async def test_counts_every_call_in_the_block_including_spawned_tasks(self):
        outside = fake("gpt-6.1-sol", 999, 999)
        with collect_llm_usage() as collector:
            await fake("gpt-6.1-sol", 3000, 200, cached=1024).ainvoke("q")
            await asyncio.gather(asyncio.create_task(fake("gpt-6-luna", 800, 50).ainvoke("q")),
                                 fake("gpt-6-luna", 700, 40).ainvoke("q"))
        await outside.ainvoke("not counted")
        by_model = {u["model"]: u for u in collector.snapshot()}
        self.assertEqual(by_model["gpt-6.1-sol"], {"provider": "openai", "model": "gpt-6.1-sol", "input_tokens": 3000,
                                                   "cached_input_tokens": 1024, "output_tokens": 200, "calls": 1})
        self.assertEqual(by_model["gpt-6-luna"]["input_tokens"], 1500)
        self.assertEqual(by_model["gpt-6-luna"]["calls"], 2)

    def test_calls_no_node_recorded_are_reported_and_priced(self):
        # sql_gen recorded itself; table selection (another Sol call) did not.
        nodes = [{"node_name": "sql_gen", "provider": "openai", "model": "gpt-6.1-sol",
                  "input_tokens": 3000, "output_tokens": 200, "total_tokens": 3200, "calls": 1, "latency_ms": 2000}]
        llm = [{"provider": "openai", "model": "gpt-6.1-sol", "input_tokens": 5000,
                "cached_input_tokens": 0, "output_tokens": 260, "calls": 2}]
        usage = answer_usage(nodes, 4000, llm)
        other = [n for n in usage["nodes"] if n["node"] == "other_calls"]
        self.assertEqual(len(other), 1)
        self.assertEqual((other[0]["input_tokens"], other[0]["output_tokens"], other[0]["calls"]), (2000, 60, 1))
        self.assertIsNone(other[0]["latency_ms"])
        self.assertEqual(usage["input_tokens"], 5000)
        self.assertAlmostEqual(usage["estimated_cost_usd"], round((5000 * 2.0 + 260 * 10.0) / 1_000_000, 6))
        self.assertTrue(usage["cost_complete"])

    def test_an_unpriced_model_anywhere_in_the_run_makes_the_cost_incomplete(self):
        llm = [{"provider": "openai", "model": "gpt-6-luna", "input_tokens": 100, "output_tokens": 10, "calls": 1},
               {"provider": "anthropic", "model": "some-claude", "input_tokens": 100, "output_tokens": 10, "calls": 1}]
        self.assertFalse(answer_usage([], 1000, llm)["cost_complete"])


class MeasureNodeCallsTest(unittest.IsolatedAsyncioTestCase):
    async def test_records_the_block_as_one_node_under_its_operation_model(self):
        state = {}
        with measure_node_calls(state, "select_table", "select_table"):
            await fake("gpt-6.1-sol", 1500, 30).ainvoke("which tables?")
        (event,) = get_node_events(state)
        self.assertEqual(event["node_name"], "select_table")
        self.assertEqual((event["provider"], event["model"]), ("openai", "gpt-6.1-sol"))
        self.assertGreaterEqual(event["latency_ms"], 0)

    async def test_an_error_in_the_block_propagates_unchanged(self):
        state = {}
        with self.assertRaises(KeyError):
            with measure_node_calls(state, "select_table", "no.such_operation"):
                raise KeyError("from the call")
        self.assertEqual(get_node_events(state), [])  # unknown operation: not recorded, not raised


class HealthEventAgreesWithApiTest(unittest.TestCase):
    def test_health_metrics_and_usage_block_report_the_same_run(self):
        from agent.utils.agent_health_service import build_query_event
        nodes = [{"node_name": "sql_gen", "provider": "openai", "model": "gpt-6.1-sol",
                  "input_tokens": 3000, "output_tokens": 200, "total_tokens": 3200, "calls": 1, "latency_ms": 2000}]
        llm = [{"provider": "openai", "model": "gpt-6.1-sol", "input_tokens": 3700, "cached_input_tokens": 0,
                "output_tokens": 230, "calls": 2},
               {"provider": "openai", "model": "gpt-6-luna", "input_tokens": 1100, "cached_input_tokens": 0,
                "output_tokens": 60, "calls": 1}]
        result = {"node_events": nodes, "llm_usage": llm, "response": "ok", "is_answered": True}
        event = build_query_event(result=result, agent_id="a", owner_id="o", user_id="u",
                                  session_id="s", chat_id="c", latency_ms=4000)
        usage = answer_usage(nodes, 4000, llm)
        self.assertEqual(event["metrics"]["input_tokens"], usage["input_tokens"])
        self.assertEqual(event["metrics"]["output_tokens"], usage["output_tokens"])
        stored = sum(n["estimated_cost_usd"] or 0 for n in event["node_data"])
        self.assertAlmostEqual(stored, usage["estimated_cost_usd"], places=6)
        self.assertEqual({n["node_name"] for n in event["node_data"]}, {"sql_gen", "other_calls"})


if __name__ == "__main__":
    unittest.main()
