"""Actual selector/node/REST bodies with synthetic boundaries; no external calls."""
import asyncio
from contextlib import ExitStack, nullcontext
import importlib.util
import json
import re
import socket
import sys
import types
import unittest
import uuid
from unittest.mock import AsyncMock, Mock, patch

from fastapi import BackgroundTasks, Depends, HTTPException, Path, Query
from fastapi.responses import JSONResponse
from starlette.requests import Request
from access_policy_harness import BACKEND, load_function, load_policy, modules, policy_record, state

sys.path.insert(0, str(BACKEND))
from agent.utils.model_profiles import ModelConfigurationError

FLAGS = {'orders': True, 'order_status_history': False}
DESCRIPTIONS = {'orders': 'current order status', 'order_status_history': 'status changes',
                'unknown_table': 'not in the verified policy'}


class SelectionPolicyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for target, name in [(socket, 'create_connection'), (socket.socket, 'connect'),
                             (socket.socket, 'connect_ex')]:
            self.stack.enter_context(patch.object(target, name, side_effect=AssertionError('External network forbidden')))
        self.policy = load_policy()
        self.select = AsyncMock(return_value=('ignored model descriptions', ['orders']))
        self.config = AsyncMock(return_value=None)
        self.examples = AsyncMock(return_value=[])
        self.fewshots = AsyncMock(return_value=types.SimpleNamespace(get_similar_examples=self.examples))
        self.introspect = Mock(side_effect=AssertionError('Unscoped source introspection reached'))
        self.selector = load_function('agent/nodes/select_table_and_fewshots.py', 'node_select_and_fewshots',
            ModelConfigurationError=ModelConfigurationError, asyncio=asyncio, select_tables=self.select, get_agent_node_config=self.config,
            get_few_shot_service=self.fewshots, build_few_shot_examples_string=lambda value: value,
            get_table_descriptions_and_selected_tables=self.introspect,
            measure_node_calls=lambda *args: nullcontext())

    async def run_selector(self, response=None, *, descriptions=DESCRIPTIONS,
                           selected=None, metadata_description=None):
        record = response if response is not None else policy_record(FLAGS)
        if metadata_description is not None:
            record['record'].description = metadata_description
        fetch = AsyncMock(return_value=record)
        s = state()
        s.update(query='orders by status bar chart', refined_query='orders by status',
                 table_descriptions=descriptions, selected_tables=selected)
        with modules(self.policy, fetch):
            sys.modules['agent.db_utils.table_description_db_utils'].get_table_names_from_db = self.introspect
            out = await self.selector(s)
        return out, fetch

    def assert_denied(self, out):
        self.assertIs(out['is_answered'], False)
        self.assertEqual(out['sql_query'], '')
        self.assertEqual(out['db_result'], [])
        self.assertIsNone(out['graph_json'])

    async def test_invalid_model_config_never_becomes_catalog_fallback(self):
        self.config.side_effect = ModelConfigurationError("incomplete stored binding")
        with self.assertRaisesRegex(ModelConfigurationError, "incomplete"):
            await self.run_selector()
        self.select.assert_not_called()
        self.fewshots.assert_not_called()
        self.introspect.assert_not_called()

    async def test_vector_configuration_error_never_becomes_empty_fewshots(self):
        self.examples.side_effect = ModelConfigurationError("vector model/dimension mismatch")
        with self.assertRaisesRegex(ModelConfigurationError, "dimension"):
            await self.run_selector()
        self.select.assert_awaited_once()
        self.introspect.assert_not_called()

    async def test_description_catalog_is_filtered_before_selection_and_allowed_positive(self):
        out, fetch = await self.run_selector()
        self.assertEqual(json.loads(self.select.await_args.args[1]), [{'orders': 'current order status'}])
        self.assertEqual(out['selected_tables'], ['orders'])
        self.assertEqual(out['table_descriptions'], {'orders': 'current order status'})
        self.assertEqual(fetch.await_count, 1)
        self.examples.assert_awaited_once()
        self.introspect.assert_not_called()

    async def test_invalid_or_foreign_policy_stops_before_selector_fewshots_or_source(self):
        cases = [{}, {'status': False}, policy_record(None), policy_record({}),
                 policy_record({'orders': 1}), policy_record({'orders': 'true'}),
                 policy_record(FLAGS, agent='other'), policy_record(FLAGS, db='other'),
                 policy_record('{bad-json')]
        for record in cases:
            with self.subTest(record=record):
                out, _ = await self.run_selector(record)
                self.assert_denied(out)
                self.assertTrue(out['access_policy_error'])
        self.select.assert_not_called()
        self.config.assert_not_called()
        self.fewshots.assert_not_called()
        self.introspect.assert_not_called()

    async def test_verified_all_false_is_restricted_not_unknown_policy(self):
        out, _ = await self.run_selector(policy_record({'orders': False}))
        self.assert_denied(out)
        self.assertEqual(out['access_denied_tables'], ['orders'])
        self.assertFalse(out['access_policy_error'])
        self.select.assert_not_called()
        self.fewshots.assert_not_called()
        self.introspect.assert_not_called()

    async def test_preselected_mixed_or_unknown_denied_before_all_work(self):
        for selected in [['orders', 'order_status_history'], ['unknown_table']]:
            with self.subTest(selected=selected):
                out, _ = await self.run_selector(selected=selected)
                self.assert_denied(out)
                self.assertTrue(out['access_denied_tables'])
        self.select.assert_not_called()
        self.fewshots.assert_not_called()
        out, _ = await self.run_selector(selected=['public.orders'])
        self.assertEqual(out['selected_tables'], ['public.orders'])
        self.assertEqual(list(out['table_descriptions']), ['orders'])
        self.introspect.assert_not_called()

    async def test_runtime_database_binding_wins_before_downstream_work(self):
        fetch = AsyncMock(return_value=policy_record(FLAGS))
        s = state()
        s.update(query='orders', table_descriptions=DESCRIPTIONS)
        s['runtime_db_details']['db_id'] = 'runtime-other-db'
        with modules(self.policy, fetch):
            out = await self.selector(s)
        self.assert_denied(out)
        self.assertTrue(out['access_policy_error'])
        self.assertEqual(fetch.await_args.kwargs['db_id'], 'runtime-other-db')
        self.select.assert_not_called()
        self.fewshots.assert_not_called()
        self.introspect.assert_not_called()

    async def test_inherited_denial_is_terminal_before_even_policy_lookup(self):
        for denial in [{'access_policy_error': True}, {'access_denied_tables': ['order_status_history']}]:
            with self.subTest(denial=denial):
                fetch = AsyncMock(return_value=policy_record(FLAGS))
                s = state()
                s.update(denial)
                with modules(self.policy, fetch):
                    out = await self.selector(s)
                self.assert_denied(out)
                fetch.assert_not_called()
        self.select.assert_not_called()
        self.config.assert_not_called()
        self.fewshots.assert_not_called()
        self.introspect.assert_not_called()

    async def test_mixed_model_selection_is_denial_not_silent_filter_or_fallback(self):
        for selected in [['orders', 'order_status_history'], ['unknown_table'], [], None]:
            with self.subTest(selected=selected):
                self.select.return_value = ('untrusted', selected)
                out, _ = await self.run_selector()
                self.assert_denied(out)
        self.assertEqual(self.select.await_count, 4)
        self.fewshots.assert_not_called()
        self.introspect.assert_not_called()

    async def test_exception_fallback_stays_within_verified_catalog_and_domain_error_escapes(self):
        self.select.side_effect = RuntimeError('synthetic selector transport failure')
        out, _ = await self.run_selector()
        self.assertEqual(out['selected_tables'], ['orders'])
        self.assertEqual(list(out['table_descriptions']), ['orders'])
        self.select.side_effect = self.policy.TableAccessPolicyError('synthetic domain failure')
        out, _ = await self.run_selector()
        self.assert_denied(out)
        self.assertTrue(out['access_policy_error'])
        self.introspect.assert_not_called()

    async def test_metadata_descriptions_and_absent_description_introspection_fallback_are_scoped(self):
        out, fetch = await self.run_selector(descriptions={}, metadata_description=[DESCRIPTIONS])
        self.assertEqual(fetch.await_count, 2)
        self.assertEqual(json.loads(self.select.await_args.args[1]), [{'orders': 'current order status'}])
        self.select.reset_mock()
        out, _ = await self.run_selector(descriptions={})
        self.assertEqual(out['selected_tables'], ['orders'])
        self.assertEqual(out['table_descriptions'], {})
        self.select.assert_not_called()
        self.introspect.assert_not_called()
        self.fewshots.reset_mock()
        first = policy_record(FLAGS)
        second = policy_record(FLAGS, db='foreign')
        second['record'].description = DESCRIPTIONS
        with modules(self.policy, AsyncMock(side_effect=[first, second])):
            s = state()
            s.update(table_descriptions={}, query='orders')
            out = await self.selector(s)
        self.assert_denied(out)
        self.select.assert_not_called()
        self.fewshots.assert_not_called()

    async def test_actual_nonstream_api_returns_canonical_denial_without_generation_or_execution(self):
        schema_spec = importlib.util.spec_from_file_location('synthetic_chat_schema', BACKEND/'api/v1/schemas/chat.py')
        schemas = importlib.util.module_from_spec(schema_spec)
        schema_spec.loader.exec_module(schemas)
        data_block = load_function('agent/utils/common_utils.py', 'build_data_block')
        source_names = load_function('api/v1/utils/chat_helper.py', '_tables_referenced_in_sql', re=re)
        response_builder = load_function('api/v1/utils/chat_helper.py', 'build_chat_response',
            build_data_block=data_block, _tables_referenced_in_sql=source_names)
        forbidden = Mock(side_effect=AssertionError('Forbidden generation/execution boundary'))
        gen = load_function('agent/nodes/sql_gen.py', 'node_sql_gen', get_agent_node_config=forbidden)
        execute = load_function('agent/nodes/sql_exec.py', 'node_sql_exec', try_exec_sql=forbidden)
        failure = load_function('agent/utils/answerability.py', 'failure_response')
        final = load_function('agent/nodes/final_answer.py', 'node_final_answer',
                              failure_response=failure, get_agent_node_config=forbidden)
        graph_route = load_function('agent/runner.py', 'route_after_final_answer')

        async def actual_node_pipeline(**kwargs):
            s = state()
            s.update(query=kwargs['query'], refined_query=kwargs['query'],
                     table_descriptions=DESCRIPTIONS, include_graph_output=True)
            out = await self.selector(s)
            out = await execute(await gen(out))
            out = await final(out)
            self.assertEqual(graph_route(out), 'END')
            return out

        endpoint = load_function('api/v1/routers/chat.py', 'chat_with_agent',
            Path=Path, Query=Query, Depends=Depends, BackgroundTasks=BackgroundTasks,
            ChatRequest=schemas.ChatRequest, Request=Request,
            get_api_key_or_session=lambda: {}, require_agent_permission=lambda *args: lambda: {},
            HTTPException=HTTPException, ModelConfigurationError=ModelConfigurationError,
            JSONResponse=JSONResponse, uuid=uuid, asyncio=asyncio,
            get_agent_with_visibility=AsyncMock(return_value=(object(), True, True, True)),
            apply_agent_answer_settings=lambda *args: {}, get_owner_email_by_agent_id=AsyncMock(return_value='synthetic'),
            enforce_query_cap=AsyncMock(), demo_question_user=lambda *args: None,
            reserve_demo_question_or_refuse=AsyncMock(), close_demo_question=AsyncMock(),
            ensure_session_belongs_to_agent=AsyncMock(),
            get_past_messages_safe=AsyncMock(return_value={'past_messages': [], 'session_id': 'synthetic-session'}),
            get_agent_runtime_db=AsyncMock(return_value=({'db_id': 'synthetic-db'}, 0)),
            run_agent_flow=actual_node_pipeline, _generate_follow_up_safe=AsyncMock(return_value=None),
            maybe_upload_csv_export=AsyncMock(return_value=None), persist_chat_logs=AsyncMock(),
            persist_health_event=AsyncMock(), build_chat_response=response_builder,
            answer_usage=lambda *args: None, get_node_events=lambda result: [],
            _owner_credential_error=AsyncMock(return_value=None))
        body = schemas.ChatRequest(query='orders by status bar chart', chart_output=True, debug_info=True, follow_up=False)
        for record, selected in [(policy_record(FLAGS), ['orders', 'order_status_history']),
                                 (policy_record(None), ['orders'])]:
            with self.subTest(policy=record):
                self.select.return_value = ('ignored', selected)
                with modules(self.policy, AsyncMock(return_value=record)), patch.dict(sys.modules, {
                    'agent.utils.common_utils': types.SimpleNamespace(serialize_db_value=lambda value: value)}):
                    response = await endpoint(agent_id='synthetic-agent', stream=False, body=body,
                                              auth={'auth_type': 'master_api_key'}, user={})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.media_type, 'application/json')
                payload = json.loads(response.body)
                self.assertIs(payload['is_answered'], False)
                self.assertIn('restricted' if record['record'].entry_flags else 'could not be verified', payload['response'])
                self.assertEqual(payload['debug_info']['sql_query'], '')
                self.assertEqual(payload['debug_info']['db_result']['rows'], [])
                self.assertIsNone(payload['graph_output'])
                self.assertIsNone(payload['chart_output'])
        self.config.side_effect = ModelConfigurationError('Incomplete stored model binding')
        with modules(self.policy, AsyncMock(return_value=policy_record(FLAGS))):
            with self.assertRaises(HTTPException) as caught:
                await endpoint(agent_id='synthetic-agent', stream=False, body=body,
                               auth={'auth_type': 'master_api_key'}, user={})
        self.assertEqual(caught.exception.status_code, 400)
        self.assertEqual(caught.exception.detail['code'], 'model_configuration_error')
        self.assertIn('Incomplete', caught.exception.detail['message'])
        forbidden.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
