"""Bring-your-own-key policy: owner keys are used everywhere, errors never fall back.

Synthetic keys and fake provider classes only; nothing here reaches a provider or database.
"""
import asyncio
import os
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

from access_policy_harness import BACKEND

sys.path.insert(0, str(BACKEND))
from agent.utils import model_profiles, provider_key_scope as pks  # noqa: E402
from agent.utils.model_profiles import ModelConfigurationError, ProviderCredentialError  # noqa: E402
from agent.utils import owner_credential_utils as ocu  # noqa: E402

PLATFORM_KEY = "sk-synthetic-platform"
OWNER_KEY = "sk-synthetic-owner"
# Product modules build (never connect) a metadata engine at import time.
SYNTHETIC_METADATA = {"POSTGRES_USER": "synthetic", "POSTGRES_PASSWORD": "synthetic",
                      "POSTGRES_HOST": "127.0.0.1", "POSTGRES_PORT": "5432",
                      "POSTGRES_DB_NAME": "synthetic"}


class CapturingChat:
    """Stands in for a provider SDK class; records the key it was built with."""
    built = []

    def __init__(self, **kwargs):
        CapturingChat.built.append(kwargs)
        self.kwargs = kwargs

    def with_structured_output(self, *args, **kwargs):
        from langchain_core.runnables import RunnableLambda
        return RunnableLambda(lambda value: value)


def fake_provider_module():
    return types.SimpleNamespace(CapturingChat=CapturingChat)


class Base(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        system = {k: os.environ[k] for k in ("SystemRoot", "WINDIR", "TEMP", "TMP") if k in os.environ}
        env = patch.dict(os.environ, {**system, **SYNTHETIC_METADATA, "OPENAI_API_KEY": PLATFORM_KEY},
                         clear=True)
        env.start()
        self.addCleanup(env.stop)
        CapturingChat.built = []
        providers = patch.dict(model_profiles.PROVIDERS,
                               {"openai": ("fake_provider_module", "CapturingChat", "OPENAI_API_KEY")})
        providers.start()
        self.addCleanup(providers.stop)
        modules = patch.dict(sys.modules, {"fake_provider_module": fake_provider_module()})
        modules.start()
        self.addCleanup(modules.stop)

    def owners(self, sources, keys):
        """sources: owner -> 'own'|'platform'; keys: owner -> {provider: (key, is_valid)}."""
        async def source(owner_id):
            default = pks.deployment_default_source()
            return sources.get(owner_id, default) if owner_id else default

        async def load(owner_id):
            return dict(keys.get(owner_id, {})), {}

        for target, fake in ((pks, "owner_key_source"), (pks, "_load_owner_keys")):
            p = patch.object(target, fake, side_effect=source if fake == "owner_key_source" else load)
            p.start()
            self.addCleanup(p.stop)


class EnvKeyTests(Base):
    def test_unbound_platform_default_reads_environment_unchanged(self):
        self.assertEqual(pks.env_key_for("openai", "OPENAI_API_KEY"), PLATFORM_KEY)

    def test_unbound_own_default_refuses_instead_of_using_platform_key(self):
        os.environ["DEFAULT_PROVIDER_KEY_SOURCE"] = "own"
        with self.assertRaises(ProviderCredentialError) as caught:
            pks.env_key_for("openai", "OPENAI_API_KEY")
        self.assertEqual(caught.exception.code, "provider_key_unbound")

    def test_invalid_deployment_default_is_a_configuration_error(self):
        os.environ["DEFAULT_PROVIDER_KEY_SOURCE"] = "sometimes"
        with self.assertRaises(ModelConfigurationError):
            pks.env_key_for("openai", "OPENAI_API_KEY")

    async def test_own_scope_answers_with_owner_key_and_errors_name_the_fix(self):
        self.owners({"byok@example.test": "own"},
                    {"byok@example.test": {"openai": (OWNER_KEY, True), "groq": ("gsk-x", False)}})
        async with pks.owner_key_scope("byok@example.test"):
            self.assertEqual(pks.env_key_for("openai", "OPENAI_API_KEY"), OWNER_KEY)
            with self.assertRaises(ProviderCredentialError) as missing:
                pks.env_key_for("google", "GOOGLE_API_KEY")
            with self.assertRaises(ProviderCredentialError) as invalid:
                pks.env_key_for("groq", "GROQ_API_KEY")
        self.assertEqual(missing.exception.code, "provider_key_missing")
        self.assertIn("Add your Google API key under Credentials", str(missing.exception))
        self.assertEqual(invalid.exception.code, "provider_key_invalid")
        for error in (missing.exception, invalid.exception):
            self.assertNotIn("sk-", str(error))
            self.assertIsInstance(error, ModelConfigurationError)
        # The binding ends with the scope.
        self.assertEqual(pks.env_key_for("openai", "OPENAI_API_KEY"), PLATFORM_KEY)

    async def test_platform_scope_keeps_environment_key(self):
        self.owners({"managed@example.test": "platform"}, {})
        async with pks.owner_key_scope("managed@example.test"):
            self.assertEqual(pks.env_key_for("openai", "OPENAI_API_KEY"), PLATFORM_KEY)

    async def test_unreadable_stored_key_is_reported_not_skipped(self):
        p = patch.object(pks, "owner_key_source", AsyncMock(return_value="own"))
        q = patch.object(pks, "_load_owner_keys", AsyncMock(return_value=({}, {"openai": "provider_key_unreadable"})))
        with p, q:
            async with pks.owner_key_scope("byok@example.test"):
                with self.assertRaises(ProviderCredentialError) as caught:
                    pks.env_key_for("openai", "OPENAI_API_KEY")
        self.assertEqual(caught.exception.code, "provider_key_unreadable")


class FactoryAndCallSiteTests(Base):
    """The previously unthreaded sites build clients with no key; the scope must decide."""

    async def test_factory_without_key_uses_owner_key_under_own_scope(self):
        self.owners({"byok@example.test": "own"}, {"byok@example.test": {"openai": (OWNER_KEY, True)}})
        conf = {"provider": "openai", "model": "gpt-6-luna"}
        async with pks.owner_key_scope("byok@example.test"):
            model_profiles.build_chat_model(conf)
        model_profiles.build_chat_model(conf)  # unbound, platform default
        self.assertEqual([c["api_key"] for c in CapturingChat.built], [OWNER_KEY, PLATFORM_KEY])

    async def test_factory_without_owner_key_fails_instead_of_platform_fallback(self):
        self.owners({"byok@example.test": "own"}, {})
        async with pks.owner_key_scope("byok@example.test"):
            with self.assertRaises(ProviderCredentialError):
                model_profiles.build_chat_model({"provider": "openai", "model": "gpt-6-luna"})
        self.assertEqual(CapturingChat.built, [])

    async def test_actual_table_selection_chain_is_built_with_owner_key(self):
        from agent.utils import langchain_utils
        self.owners({"byok@example.test": "own"}, {"byok@example.test": {"openai": (OWNER_KEY, True)}})
        with patch.object(langchain_utils, "operation_config",
                          return_value=model_profiles.validate_binding({"provider": "openai", "model": "gpt-6.1-sol"})):
            async with pks.owner_key_scope("byok@example.test"):
                langchain_utils.get_table_selection_chain(None)
        self.assertEqual([c["api_key"] for c in CapturingChat.built], [OWNER_KEY])

    async def test_actual_description_builder_uses_agent_owner_key_or_fails(self):
        from api.v1.utils import description_jobs_helper as djh
        crud = types.ModuleType("chatbot_management.db_utils.bot_crud_db_utils")
        crud.get_owner_email_by_agent_id = AsyncMock(return_value="byok@example.test")
        self.owners({"byok@example.test": "own"}, {"byok@example.test": {"openai": (OWNER_KEY, True)}})
        with patch.dict(sys.modules, {"chatbot_management.db_utils.bot_crud_db_utils": crud}):
            await djh._build_llm("synthetic-agent")
            self.assertEqual([c["api_key"] for c in CapturingChat.built], [OWNER_KEY])
            crud.get_owner_email_by_agent_id.return_value = "nokey@example.test"
            with patch.object(pks, "owner_key_source", AsyncMock(return_value="own")):
                with self.assertRaises(ProviderCredentialError) as caught:
                    await djh._build_llm("synthetic-agent")
        self.assertEqual(caught.exception.code, "provider_key_missing")
        self.assertEqual(len(CapturingChat.built), 1)

    async def test_scope_reaches_actual_langgraph_nodes_and_child_tasks(self):
        from typing import TypedDict
        from langgraph.graph import StateGraph, START, END

        class S(TypedDict, total=False):
            seen: list

        async def async_node(state):
            child = await asyncio.create_task(asyncio.sleep(0, result=pks.env_key_for("openai", "OPENAI_API_KEY")))
            return {"seen": [pks.env_key_for("openai", "OPENAI_API_KEY"), child]}

        def sync_node(state):
            return {"seen": state["seen"] + [pks.env_key_for("openai", "OPENAI_API_KEY")]}

        graph = StateGraph(S)
        graph.add_node("a", async_node)
        graph.add_node("b", sync_node)
        graph.add_edge(START, "a")
        graph.add_edge("a", "b")
        graph.add_edge("b", END)
        app = graph.compile()
        self.owners({"byok@example.test": "own"}, {"byok@example.test": {"openai": (OWNER_KEY, True)}})
        async with pks.owner_key_scope("byok@example.test"):
            result = await app.ainvoke({})
        self.assertEqual(result["seen"], [OWNER_KEY, OWNER_KEY, OWNER_KEY])


class ExplicitLookupTests(Base):
    async def test_own_owner_without_key_never_gets_platform_key(self):
        self.owners({"byok@example.test": "own"}, {})
        for call in (lambda: ocu.get_owner_api_key_for_provider("byok@example.test", "openai"),
                     lambda: ocu.get_llm_api_key("byok@example.test", "gpt-6-luna", "openai")):
            with self.assertRaises(ProviderCredentialError):
                await call()

    async def test_own_owner_gets_owner_key_with_owner_source(self):
        self.owners({"byok@example.test": "own"}, {"byok@example.test": {"openai": (OWNER_KEY, True)}})
        self.assertEqual(await ocu.get_owner_api_key_for_provider("byok@example.test", "openai", return_source=True),
                         (OWNER_KEY, "owner-key"))

    async def test_platform_owner_keeps_existing_fallback(self):
        self.owners({"managed@example.test": "platform"}, {})
        with patch.object(ocu, "_lookup_owner_key", AsyncMock(return_value=None)):
            self.assertEqual(
                await ocu.get_owner_api_key_for_provider("managed@example.test", "openai", return_source=True),
                (PLATFORM_KEY, "platform-key"))

    async def test_scope_for_another_owner_is_not_reused(self):
        self.owners({"a@example.test": "own", "b@example.test": "own"},
                    {"a@example.test": {"openai": (OWNER_KEY, True)}})
        async with pks.owner_key_scope("a@example.test"):
            with self.assertRaises(ProviderCredentialError):
                await ocu.get_owner_api_key_for_provider("b@example.test", "openai")


class OwnerResolutionTests(Base):
    """A browser session may act only on its own credentials and owner settings."""

    def test_session_cannot_name_another_owner_but_master_key_can(self):
        from fastapi import HTTPException
        from api.v1.routers import credentials, owner_config
        session = {"auth_type": "session", "user_id": "Me@Example.test"}
        master = {"auth_type": "master_api_key"}
        for module in (credentials, owner_config):
            with self.subTest(router=module.__name__):
                self.assertEqual(module._resolve_owner(session, "me"), "me@example.test")
                self.assertEqual(module._resolve_owner(session, "ME@example.test"), "me@example.test")
                with self.assertRaises(HTTPException) as caught:
                    module._resolve_owner(session, "victim@example.test")
                self.assertEqual(caught.exception.status_code, 403)
                self.assertEqual(module._resolve_owner(master, "Other@Example.test"), "other@example.test")


class ChatErrorMappingTests(unittest.IsolatedAsyncioTestCase):
    def test_provider_auth_error_is_found_in_cause_chain(self):
        class AuthenticationError(Exception):
            status_code = 401
        try:
            try:
                raise AuthenticationError("Incorrect API key provided")
            except AuthenticationError as inner:
                raise RuntimeError("model call failed") from inner
        except RuntimeError as outer:
            self.assertTrue(pks.is_provider_auth_error(outer))
        self.assertFalse(pks.is_provider_auth_error(RuntimeError("timeout")))


if __name__ == "__main__":
    unittest.main()
