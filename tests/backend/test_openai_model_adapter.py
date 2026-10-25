"""Actual installed SDK serialization and schema parsing; no network/provider calls."""
import json
import ast
import inspect
from pathlib import Path
import sys
import unittest

import httpx
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]
from access_policy_harness import source_root
BACKEND = source_root(ROOT, Path('/app'))
sys.path.insert(0, str(BACKEND))
from agent.utils.openai_chat_kwargs import product_chat_openai


class Selection(BaseModel):
    selected_tables: list[str]


class ModelAdapterTests(unittest.TestCase):
    def test_config_and_client_use_same_checkout_or_container_source(self):
        origin = Path(inspect.getmodule(product_chat_openai).__file__).resolve()
        self.assertEqual(origin, (BACKEND/'agent/utils/openai_chat_kwargs.py').resolve())
        self.assertTrue((BACKEND/'model_config.json').is_file())
    def client(self, model, **overrides):
        self.requests = []
        def respond(request):
            payload = json.loads(request.content)
            self.requests.append((request.url.path, payload))
            call = {'name': 'Selection', 'arguments': '{"selected_tables":["orders"]}'}
            if request.url.path.endswith('/responses'):
                response = {'id': 'resp_synthetic', 'object': 'response', 'created_at': 1,
                            'model': model, 'status': 'completed', 'error': None,
                            'output': [{'type': 'function_call', 'id': 'fc_synthetic',
                                        'call_id': 'call_synthetic', 'status': 'completed', **call}],
                            'usage': {'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2}}
            else:
                response = {'id': 'chat_synthetic', 'object': 'chat.completion', 'created': 1,
                            'model': model, 'choices': [{'index': 0, 'finish_reason': 'tool_calls',
                            'message': {'role': 'assistant', 'content': None, 'tool_calls': [
                                {'id': 'call_synthetic', 'type': 'function', 'function': call}]}}],
                            'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}}
            return httpx.Response(200, json=response)
        return product_chat_openai(model=model, temperature=0, api_key='synthetic-offline',
                                   http_client=httpx.Client(transport=httpx.MockTransport(respond)), **overrides)

    def test_sol_actual_responses_tool_payload_and_parse(self):
        client = self.client('gpt-6.1-sol', top_p=0.1, logprobs=True, top_logprobs=3,
                             include=['message.output_text.logprobs'])
        result = client.with_structured_output(Selection, method='function_calling').invoke('Select tables.')
        self.assertEqual(result.selected_tables, ['orders'])
        path, payload = self.requests[0]
        self.assertEqual(path, '/v1/responses')
        self.assertEqual(payload['reasoning'], {'effort': 'low'})
        self.assertFalse(payload['store'])
        self.assertNotIn('temperature', payload)
        for field in ('top_p','logprobs','top_logprobs'):
            self.assertNotIn(field, payload)
        self.assertNotIn('message.output_text.logprobs', payload.get('include', []))
        self.assertEqual(payload['max_output_tokens'], 8192)
        self.assertEqual(payload['tools'][0]['type'], 'function')
        self.assertEqual(len(self.requests), 1)

    def test_luna_actual_chat_function_payload_and_parse(self):
        client = self.client('gpt-6-luna')
        result = client.with_structured_output(Selection, method='function_calling').invoke('Select tables.')
        self.assertEqual(result.selected_tables, ['orders'])
        path, payload = self.requests[0]
        self.assertEqual(path, '/v1/chat/completions')
        self.assertEqual(payload['reasoning_effort'], 'none')
        self.assertEqual(payload['max_completion_tokens'], 2048)
        self.assertEqual(len(self.requests), 1)

    def test_legacy_client_settings_are_preserved(self):
        client = self.client('gpt-4.1-mini')
        self.assertEqual(client.temperature, 0)
        self.assertIsNone(client.reasoning_effort)
        self.assertIsNone(client.use_responses_api)

    def test_operation_defaults_and_live_caller_imports(self):
        from agent.utils.model_profiles import load_profile
        cfg = load_profile()
        for group in ('sql_agent', 'pandas_agent', 'chart_agent', 'descriptions', 'csv_agent', 'reports'):
            for name, conf in cfg[group].items():
                self.assertEqual(conf['provider'], 'openai')
                expensive = (group, name) in {('sql_agent','db_router'), ('sql_agent','select_table'),
                                               ('sql_agent','sql_generation'), ('pandas_agent','default')}
                self.assertEqual(conf['model'], 'gpt-6.1-sol' if expensive else 'gpt-6-luna')
        for area in ('agent', 'chart_agent', 'pandas_agent', 'csv_agent', 'api/v1/utils'):
            for path in (BACKEND/area).rglob('*.py'):
                if path.name == 'openai_chat_kwargs.py' or 'scripts' in path.parts:
                    continue
                active = '\n'.join(line for line in path.read_text(encoding='utf-8').splitlines()
                                   if not line.lstrip().startswith('#'))
                self.assertNotIn('from langchain_openai import ChatOpenAI', active, str(path))


if __name__ == '__main__':
    unittest.main()
