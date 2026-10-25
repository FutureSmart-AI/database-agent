"""No provider calls: a trusted internal caller's chart request runs on platform keys.

Document Intelligence calls the Chart API with its own owner ids. On the hosted
bring-your-own-key deployment (DEFAULT_PROVIDER_KEY_SOURCE=own) an owner with no
Database Agent configuration failed every chart with "No OpenAI API key is configured
for this workspace" (measured 2026-10-25: every chart on the DI sample collections).
CHART_SERVICE_KEY lets that caller prove itself; nothing changes for anyone else.
"""
import os
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

from fastapi import FastAPI
from fastapi.testclient import TestClient

import chart_agent.api.chart_api as chart_api
from agent.utils.provider_key_scope import PLATFORM, current_scope

KEY = "test-chart-service-key"


class ChartServiceKeyTests(unittest.TestCase):
    def setUp(self):
        self.seen = {}

        async def _fake_generate(csv_path, question, allowed_graphs=None, owner_id=None):
            self.seen["scope"] = current_scope()
            return {"is_direct_response": True, "response": "ok", "chart_type": None}

        self._original = chart_api.generate_graph_from_csv
        chart_api.generate_graph_from_csv = _fake_generate
        app = FastAPI()
        app.include_router(chart_api.router)
        self.client = TestClient(app)
        os.environ["CHART_SERVICE_KEY"] = KEY

    def tearDown(self):
        chart_api.generate_graph_from_csv = self._original
        os.environ.pop("CHART_SERVICE_KEY", None)

    def _post(self, headers=None):
        return self.client.post(
            "/v1/chart_agent/generate",
            data={"query": "chart this", "owner_id": "di-owner@example.com"},
            files={"file": ("vector_data.csv", b"a,b\nx,1\ny,2\n", "text/csv")},
            headers=headers or {},
        )

    def test_valid_service_key_binds_the_platform_scope_for_the_sent_owner(self):
        response = self._post({"X-Chart-Service-Key": KEY})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.seen["scope"].source, PLATFORM)
        self.assertEqual(self.seen["scope"].owner_id, "di-owner@example.com")

    def test_no_service_key_leaves_the_owner_policy_unchanged(self):
        response = self._post()
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self.seen["scope"])

    def test_wrong_service_key_is_refused_not_downgraded(self):
        response = self._post({"X-Chart-Service-Key": "nope"})
        self.assertEqual(response.status_code, 401)
        self.assertNotIn("scope", self.seen)

    def test_a_key_presented_to_a_deployment_without_one_is_refused(self):
        os.environ.pop("CHART_SERVICE_KEY")
        response = self._post({"X-Chart-Service-Key": KEY})
        self.assertEqual(response.status_code, 401)

    def test_scope_does_not_leak_past_the_request(self):
        self._post({"X-Chart-Service-Key": KEY})
        self.assertIsNone(current_scope())


class PlatformScopeKeyLookupTests(unittest.TestCase):
    """The production condition itself: DEFAULT_PROVIDER_KEY_SOURCE=own and an owner
    with no Database Agent configuration or stored key."""

    def setUp(self):
        import agent.utils.owner_credential_utils as creds
        import agent.utils.provider_key_scope as scope_module

        self.creds, self.scope_module = creds, scope_module
        self._saved = (creds._lookup_owner_key, scope_module.owner_key_source, scope_module._load_owner_keys,
                       os.environ.get("DEFAULT_PROVIDER_KEY_SOURCE"), os.environ.get("OPENAI_API_KEY"))

        async def _no_stored_key(owner_id, provider):
            return None

        async def _no_stored_choice(owner_id):
            return scope_module.deployment_default_source()

        async def _no_owner_keys(owner_id):
            return {}, {}

        creds._lookup_owner_key = _no_stored_key
        scope_module._load_owner_keys = _no_owner_keys
        scope_module.owner_key_source = _no_stored_choice
        os.environ["DEFAULT_PROVIDER_KEY_SOURCE"] = "own"
        os.environ["OPENAI_API_KEY"] = "sk-platform-test"

    def tearDown(self):
        (self.creds._lookup_owner_key, self.scope_module.owner_key_source,
         self.scope_module._load_owner_keys, default, key) = self._saved
        for name, value in (("DEFAULT_PROVIDER_KEY_SOURCE", default), ("OPENAI_API_KEY", key)):
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def _lookup(self):
        import asyncio
        return asyncio.run(self.creds.get_owner_api_key_for_provider("di-owner@example.com", "openai"))

    def test_unbound_request_fails_closed_as_before(self):
        from agent.utils.model_profiles import ProviderCredentialError
        with self.assertRaises(ProviderCredentialError):
            self._lookup()

    def test_platform_scope_uses_the_platform_key(self):
        import asyncio

        async def _inside():
            async with self.scope_module.platform_key_scope("di-owner@example.com"):
                return await self.creds.get_owner_api_key_for_provider("di-owner@example.com", "openai")

        self.assertEqual(asyncio.run(_inside()), "sk-platform-test")


if __name__ == "__main__":
    unittest.main()
