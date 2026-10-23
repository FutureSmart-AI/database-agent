"""MCP adapter contract tests through real MCP client sessions (in-memory and stdio).

No product API, model or database is involved: tests/mcp/fake_api.py stands in for the REST
API. They check what the adapter itself is responsible for: tool schemas, credential
selection, structured results, conversation continuation, visibility and error mapping.
"""
import json
import os
from pathlib import Path
import sys
import unittest

import httpx
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.shared.memory import create_connected_server_and_client_session

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "mcp-server"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from database_agent_mcp.config import ConfigError, Settings, parse_agent_keys  # noqa: E402
from database_agent_mcp.server import build_server  # noqa: E402
from fake_api import OPERATOR_KEY, FakeApi, serve  # noqa: E402

URL = "http://127.0.0.1:18000/nl2sql/api"


def transport(api):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        status, payload = api.handle(request.method, request.url.path, request.headers.get("X-API-Key"), body)
        return httpx.Response(status, json=payload)
    return httpx.MockTransport(handler)


class ConfigTests(unittest.TestCase):
    def test_agent_keys_parse_and_reject_malformed_without_echoing_secrets(self):
        self.assertEqual(parse_agent_keys(" A=k1,\nB = k2 ,"), {"A": "k1", "B": "k2"})
        for bad in ("A", "=secret-value", "A=", "A=x,A=y"):
            with self.subTest(bad=bad), self.assertRaises(ConfigError) as caught:
                parse_agent_keys(bad)
            self.assertNotIn("secret-value", str(caught.exception))

    def test_requires_a_credential_and_refuses_plain_http_to_remote_hosts(self):
        with self.assertRaises(ConfigError):
            Settings.from_env({})
        with self.assertRaises(ConfigError):
            Settings.from_env({"DATABASE_AGENT_URL": "http://agent.example.com/nl2sql/api",
                               "DATABASE_AGENT_API_KEY": "k"})
        settings = Settings.from_env({"DATABASE_AGENT_URL": "https://agent.example.com/nl2sql/api/",
                                      "DATABASE_AGENT_AGENT_KEYS": "A=k"})
        self.assertEqual(settings.api_url, "https://agent.example.com/nl2sql/api")
        self.assertNotIn("'k'", repr(settings))

    def test_agent_key_wins_and_missing_credential_is_explicit(self):
        settings = Settings(agent_keys={"A": "ka"}, operator_key="op")
        self.assertEqual(settings.credential_for("A"), ("ka", "agent_key"))
        self.assertEqual(settings.credential_for("B"), ("op", "operator_key"))
        with self.assertRaisesRegex(ConfigError, "No credential configured for agent B"):
            Settings(agent_keys={"A": "ka"}).credential_for("B")


class InMemoryToolTests(unittest.IsolatedAsyncioTestCase):
    async def call(self, settings, name, arguments=None, api=None):
        self.api = api or getattr(self, "api", None) or FakeApi()
        server = build_server(settings, transport=transport(self.api))
        async with create_connected_server_and_client_session(server) as client:
            return await client.call_tool(name, arguments or {})

    async def test_tools_publish_input_and_output_schemas(self):
        server = build_server(Settings(agent_keys={"NL2SQL_SALES": "key-sales"}), transport=transport(FakeApi()))
        async with create_connected_server_and_client_session(server) as client:
            tools = {t.name: t for t in (await client.list_tools()).tools}
        self.assertEqual(set(tools), {"list_agents", "ask_database", "list_conversations", "get_conversation"})
        self.assertEqual(tools["ask_database"].inputSchema["required"], ["agent_id", "question"])
        self.assertIn("result", tools["ask_database"].outputSchema["properties"])
        self.assertTrue(tools["list_agents"].annotations.readOnlyHint)
        self.assertFalse(tools["ask_database"].annotations.destructiveHint)

    async def test_agent_keys_list_only_their_agents_and_never_call_agentless_routes(self):
        result = await self.call(Settings(agent_keys={"NL2SQL_SALES": "key-sales", "NL2SQL_OTHER": "key-sales"}),
                                 "list_agents")
        self.assertFalse(result.isError)
        data = result.structuredContent
        self.assertEqual([a["agent_id"] for a in data["agents"]], ["NL2SQL_SALES"])
        self.assertEqual(data["agents"][0]["databases"][0]["name"], "sample_sales")
        self.assertNotIn("db_host", json.dumps(data))
        self.assertNotIn("system_prompt", json.dumps(data))
        self.assertEqual(data["unavailable"][0]["agent_id"], "NL2SQL_OTHER")
        self.assertIn("HTTP 403", data["unavailable"][0]["error"])
        self.assertNotIn(("GET", "/nl2sql/api/v1/agents", "agent"), self.api.requests)

    async def test_operator_key_lists_every_agent(self):
        result = await self.call(Settings(operator_key=OPERATOR_KEY), "list_agents")
        self.assertEqual({a["agent_id"] for a in result.structuredContent["agents"]},
                         {"NL2SQL_SALES", "NL2SQL_HIDDEN", "NL2SQL_OTHER"})
        self.assertEqual({a["credential"] for a in result.structuredContent["agents"]}, {"operator_key"})

    async def test_ask_returns_sql_rows_answer_and_chart_then_continues_the_session(self):
        settings = Settings(agent_keys={"NL2SQL_SALES": "key-sales"})
        first = await self.call(settings, "ask_database",
                                {"agent_id": "NL2SQL_SALES", "question": "Total amount by region?"})
        self.assertFalse(first.isError, first.content)
        answer = first.structuredContent
        self.assertIn("SUM(amount)", answer["sql"])
        self.assertEqual(answer["result"]["rows"], [{"region": "North", "total": "250.00"},
                                                    {"region": "South", "total": "200.00"}])
        self.assertEqual([c["name"] for c in answer["result"]["columns"]], ["region", "total"])
        self.assertEqual(answer["chart"]["type"], "bar")
        self.assertEqual(answer["tables"], ["orders"])
        self.assertTrue(answer["answered"])
        follow = await self.call(settings, "ask_database", {"agent_id": "NL2SQL_SALES", "question": "And North only?",
                                                            "session_id": answer["session_id"]})
        self.assertEqual(follow.structuredContent["session_id"], answer["session_id"])
        self.assertIn("earlier context", follow.structuredContent["answer"])
        self.assertIn(("POST", f"/nl2sql/api/v1/agents/NL2SQL_SALES/sessions/{answer['session_id']}/messages", "agent"),
                      self.api.requests)

        saved = await self.call(settings, "get_conversation",
                                {"agent_id": "NL2SQL_SALES", "session_id": answer["session_id"]})
        turns = saved.structuredContent["turns"]
        self.assertEqual([t["question"] for t in turns], ["Total amount by region?", "And North only?"])
        self.assertEqual(turns[0]["result"]["rows"][0], {"region": "North", "total": "250.00"})
        self.assertIn("SUM(amount)", turns[0]["sql"])
        listed = await self.call(settings, "list_conversations", {"agent_id": "NL2SQL_SALES"})
        self.assertEqual(listed.structuredContent["conversations"][0]["session_id"], answer["session_id"])

    async def test_max_rows_truncates_only_the_returned_copy(self):
        result = await self.call(Settings(operator_key=OPERATOR_KEY), "ask_database",
                                 {"agent_id": "NL2SQL_SALES", "question": "q", "max_rows": 1})
        rows = result.structuredContent["result"]
        self.assertEqual((rows["returned"], rows["row_count"], rows["truncated"]), (1, 2, True))
        self.assertEqual(len(result.structuredContent["chart"]["data"]), 1)

    async def test_agent_visibility_settings_hold_for_live_and_saved_results(self):
        settings = Settings(agent_keys={"NL2SQL_HIDDEN": "key-hidden"})
        live = (await self.call(settings, "ask_database", {"agent_id": "NL2SQL_HIDDEN", "question": "q"})).structuredContent
        self.assertIsNone(live["sql"])
        self.assertIsNone(live["result"])
        self.assertEqual(len(live["notes"]), 2)
        saved = (await self.call(settings, "get_conversation",
                                 {"agent_id": "NL2SQL_HIDDEN", "session_id": live["session_id"]})).structuredContent
        self.assertIsNone(saved["turns"][0]["sql"])
        self.assertIsNone(saved["turns"][0]["result"])

    async def test_authorization_failures_are_tool_errors_with_the_server_reason(self):
        api = FakeApi()
        cases = [
            (Settings(agent_keys={"NL2SQL_SALES": "revoked"}), "NL2SQL_SALES", "HTTP 401"),
            (Settings(agent_keys={"NL2SQL_OTHER": "key-sales"}), "NL2SQL_OTHER", "HTTP 403"),
            (Settings(agent_keys={"NL2SQL_SALES": "key-sales"}), "NL2SQL_OTHER", "No credential configured"),
        ]
        for settings, agent_id, expected in cases:
            with self.subTest(agent_id=agent_id, expected=expected):
                result = await self.call(settings, "ask_database", {"agent_id": agent_id, "question": "q"}, api=api)
                self.assertTrue(result.isError)
                self.assertIn(expected, result.content[0].text)
                self.assertNotIn("key-sales", result.content[0].text)
                self.assertNotIn("revoked", result.content[0].text)

    async def test_foreign_or_unknown_session_and_query_cap_are_reported(self):
        api = FakeApi()
        own = await self.call(Settings(operator_key=OPERATOR_KEY), "ask_database",
                              {"agent_id": "NL2SQL_OTHER", "question": "q"}, api=api)
        foreign = await self.call(Settings(agent_keys={"NL2SQL_SALES": "key-sales"}), "ask_database",
                                  {"agent_id": "NL2SQL_SALES", "question": "q",
                                   "session_id": own.structuredContent["session_id"]}, api=api)
        self.assertTrue(foreign.isError)
        self.assertIn("HTTP 404", foreign.content[0].text)
        api.limited.add("NL2SQL_SALES")
        capped = await self.call(Settings(agent_keys={"NL2SQL_SALES": "key-sales"}), "ask_database",
                                 {"agent_id": "NL2SQL_SALES", "question": "q"}, api=api)
        self.assertTrue(capped.isError)
        self.assertIn("Query limit reached", capped.content[0].text)

    async def test_unreachable_api_is_a_clear_tool_error(self):
        server = build_server(Settings(api_url="http://127.0.0.1:9/nl2sql/api", operator_key="op", timeout=2))
        async with create_connected_server_and_client_session(server) as client:
            result = await client.call_tool("list_agents", {})
        self.assertTrue(result.isError)
        self.assertIn("Cannot reach the Database Agent API", result.content[0].text)


class StdioEntrypointTests(unittest.IsolatedAsyncioTestCase):
    """The packaged command, launched the way Claude Code launches it, over stdio."""

    async def test_stdio_server_answers_through_the_rest_api(self):
        api = FakeApi()
        server, url = serve(api)
        self.addCleanup(server.shutdown)
        env = {**os.environ, "PYTHONPATH": str(ROOT / "mcp-server"), "DATABASE_AGENT_URL": url,
               "DATABASE_AGENT_AGENT_KEYS": "NL2SQL_SALES=key-sales"}
        env.pop("DATABASE_AGENT_API_KEY", None)
        params = StdioServerParameters(command=sys.executable, args=["-m", "database_agent_mcp"], env=env)
        async with stdio_client(params) as (read, write), ClientSession(read, write) as client:
            init = await client.initialize()
            self.assertEqual(init.serverInfo.name, "database-agent")
            agents = await client.call_tool("list_agents", {})
            self.assertEqual(agents.structuredContent["agents"][0]["agent_id"], "NL2SQL_SALES")
            answer = await client.call_tool("ask_database", {"agent_id": "NL2SQL_SALES", "question": "Totals?"})
            self.assertFalse(answer.isError)
            self.assertEqual(answer.structuredContent["result"]["row_count"], 2)

    async def test_missing_configuration_exits_with_a_message(self):
        import subprocess
        env = {k: v for k, v in os.environ.items() if not k.startswith("DATABASE_AGENT_")}
        env["PYTHONPATH"] = str(ROOT / "mcp-server")
        done = subprocess.run([sys.executable, "-m", "database_agent_mcp"], env=env, capture_output=True,
                              text=True, timeout=60, stdin=subprocess.DEVNULL)
        self.assertEqual(done.returncode, 2)
        self.assertIn("No Database Agent credential configured", done.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
