"""Actual template persistence/readers with synthetic ORM and no external calls."""
from contextlib import ExitStack
from datetime import datetime
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, patch

from access_policy_harness import BACKEND, LOG, load_function
sys.path.insert(0, str(BACKEND))
from agent.utils.model_profiles import operation_config, ModelConfigurationError
from api.v1.schemas.config import NodeConfig
from api.v1.schemas.agents import CreateAgentRequest, DEFAULT_TEMPLATE_ID


class TemplateInheritanceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for obj, name in ((socket, 'create_connection'), (socket.socket, 'connect'), (socket.socket, 'connect_ex')):
            self.stack.enter_context(patch.object(obj, name, side_effect=AssertionError('External network forbidden')))
        system = {k: os.environ[k] for k in ('SystemRoot', 'WINDIR', 'TEMP', 'TMP') if k in os.environ}
        self.stack.enter_context(patch.dict(os.environ, system, clear=True))
        self.record = None

        class Field:
            def __eq__(self, other): return self
            def is_(self, other): return self

        class Row:
            agent_id = node_name = deleted_at = Field()
            def __init__(self, **values):
                self.is_default = False
                self.deleted_at = None
                self.__dict__.update(values)

        self.session = types.SimpleNamespace(
            execute=AsyncMock(side_effect=lambda *_: types.SimpleNamespace(
                scalars=lambda: types.SimpleNamespace(first=lambda: self.record),
                scalar_one_or_none=lambda: self.record)),
            commit=AsyncMock(), add=lambda value: setattr(self, 'record', value))
        async def sessions(): yield self.session
        bindings = dict(ChatbotNodeConfig=Row, select=lambda *_: types.SimpleNamespace(where=lambda *_: None),
                        get_async_session=sessions, datetime=datetime)
        self.write = load_function('chatbot_management/db_utils/chatbot_node_db_utils.py',
                                  'upsert_node_configs_in_db', **bindings)
        self.read = load_function('agent/utils/agent_config_loader.py', 'get_agent_node_config',
                                  operation_config=operation_config, ModelConfigurationError=ModelConfigurationError, **bindings)
        spec = importlib.util.spec_from_file_location('synthetic_agent_templates', BACKEND/'api/v1/utils/agent_templates.py')
        self.templates = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'logger': types.SimpleNamespace(logger=LOG)}):
            spec.loader.exec_module(self.templates)
        self.db_module = types.SimpleNamespace(upsert_node_configs_in_db=self.write)

    async def apply(self):
        # No template unless the creator chooses one (DA-ANSWERABILITY-001).
        self.assertIsNone(CreateAgentRequest(agent_name='fresh synthetic agent').template_id)
        self.assertIsNone(DEFAULT_TEMPLATE_ID)
        request = CreateAgentRequest(agent_name='fresh synthetic agent', template_id='saas_founder')
        with patch.dict(sys.modules, {'chatbot_management.db_utils.chatbot_node_db_utils': self.db_module}):
            result = await self.templates.apply_template('synthetic-agent', request.template_id)
        self.assertTrue(result['applied'])
        self.assertEqual(result['nodes'], ['sql_gen'])
        self.assertEqual(self.session.commit.await_count, 1)

    async def settings(self):
        agent = types.SimpleNamespace(chatbot_name='synthetic', system_prompt=None, greet_message=None,
                                      debug_info=False, graph_output=True, allowed_graphs=None,
                                      max_query_execution_time=None, enable_query_caching=None,
                                      default_max_tokens=None)
        get_settings = load_function('api/v1/utils/config_helper.py', 'get_agent_config_data',
            get_chatbot_details_by_agent_id=AsyncMock(return_value=agent),
            get_node_configs_from_db=AsyncMock(return_value=[self.record]),
            operation_config=operation_config, VALID_NODE_NAMES=['sql_gen'], NODE_CONFIG_MAP={},
            HTTPException=RuntimeError)
        return (await get_settings('synthetic-user', 'synthetic-agent'))['config']['nodes'][0]

    async def test_default_template_actual_writer_to_runtime_and_settings(self):
        await self.apply()
        self.assertIsNone(self.record.provider)
        self.assertIsNone(self.record.model)
        self.assertIsNone(self.record.temperature)
        self.assertEqual(self.record.prompt, self.templates._SAAS_FOUNDER_SQL_GEN)
        self.assertIsNone(await self.read('synthetic-agent', 'sql_gen'))
        resolved = operation_config('sql_gen', await self.read('synthetic-agent', 'sql_gen'))
        self.assertEqual((resolved['provider'], resolved['model'], resolved['endpoint'], resolved['reasoning_effort']),
                         ('openai', 'gpt-6.1-sol', 'responses', 'low'))
        self.assertIsNone(resolved.get('temperature'))
        node = await self.settings()
        self.assertEqual((node['provider'], node['model'], node['temperature']), ('openai', 'gpt-6.1-sol', None))
        self.assertEqual(node['prompt'], self.record.prompt)

    async def test_existing_template_tracks_rich_file_overrides_and_single_provider(self):
        await self.apply()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'models.json'
            with patch.dict(os.environ, {'MODEL_CONFIG_PATH': str(path)}):
                path.write_text(json.dumps({'profile': 'futuresmart-recommended-v1', 'overrides': {
                    'sql_agent.sql_generation': {'provider':'openai','model':'gpt-6.1-sol',
                        'endpoint':'responses','reasoning_effort':'high'}}}))
                self.assertIsNone(await self.read('synthetic-agent','sql_gen'))
                resolved=operation_config('sql_gen',await self.read('synthetic-agent','sql_gen'))
                self.assertEqual(resolved['reasoning_effort'], 'high')
                self.assertEqual((await self.settings())['model'], 'gpt-6.1-sol')
                path.write_text(json.dumps({'profile':'futuresmart-recommended-v1', 'single_provider':{
                    'provider':'groq','model':'openai/gpt-oss-120b','temperature':0.0}}))
                resolved=operation_config('sql_gen',await self.read('synthetic-agent','sql_gen'))
                self.assertEqual((resolved['provider'],resolved['model']),('groq','openai/gpt-oss-120b'))
                self.assertEqual((await self.settings())['provider'], 'groq')

    async def test_explicit_stored_binding_preserved_and_partial_or_empty_rejected(self):
        await self.apply()
        self.record.provider='google'; self.record.model='gemini-3.8-flash';self.record.temperature=0.0
        self.assertEqual((await self.read('synthetic-agent','sql_gen'))['provider'],'google')
        for provider,model,temperature,prompt in [('google',None,None,'instructions'),
                (None,'gpt-6.1-sol',None,'instructions'),(None,None,None,None),
                (None,None,0.0,'instructions'), (None,None,None,'   '),
                (None,None,None,{'malformed':True})]:
            self.record.provider=provider;self.record.model=model
            self.record.temperature=temperature;self.record.prompt=prompt
            with self.assertRaises(ModelConfigurationError):
                await self.read('synthetic-agent','sql_gen')
        with self.assertRaises(Exception):
            NodeConfig(node_name='sql_gen',provider=None,model=None,prompt='instructions')


if __name__ == '__main__': unittest.main()
