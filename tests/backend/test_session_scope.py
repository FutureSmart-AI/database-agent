"""Saved conversations stay on their agent and under their agent's answer visibility.

1. A supplied session_id continues a conversation only on the agent that created it. History
   is read by session_id alone, so without the check a caller allowed to use agent A could
   pass a session created on agent B and have B's questions and answers replayed into A's
   model context (and appended to B's session).
2. A replayed conversation applies the agent's `show_sql_query` / `show_db_result` exactly as
   the live answer does, on every route that serves saved turns (session detail, session
   messages, CSV export) — not only in clients that choose to hide the fields.

Synthetic agents, sessions and rows; no database, network or model calls.
"""
import ast
import asyncio
import importlib.util
import json
import sys
import types
import unittest
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import BackgroundTasks, Depends, HTTPException, Path, Query
from fastapi.responses import JSONResponse
from starlette.requests import Request
from access_policy_harness import BACKEND, load_function

sys.path.insert(0, str(BACKEND))
from agent.utils.model_profiles import ModelConfigurationError

SQL = 'SELECT region, SUM(amount) FROM orders GROUP BY region'
ROWS = '[["North", 250.0], ["row-only-region", 200.0]]'  # a value that appears only in the rows


def session_store(owner_agent):
    """get_session_details as the product implements it: match on session AND agent."""
    async def get_session_details(session_id, agent_id):
        if session_id == 'session-of-b' and agent_id == owner_agent:
            return {'session_id': session_id, 'created_time': None, 'session_title': 't'}
        return None
    return AsyncMock(side_effect=get_session_details)


def session_module(**attrs):
    return {'session': types.ModuleType('session'), 'session.db_utils': types.ModuleType('session.db_utils'),
            'session.db_utils.session_db_utils': types.SimpleNamespace(**attrs)}


class SessionScopeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.guard = load_function('api/v1/utils/chat_helper.py', 'ensure_session_belongs_to_agent',
                                   HTTPException=HTTPException)
        spec = importlib.util.spec_from_file_location('synthetic_chat_schemas', BACKEND/'api/v1/schemas/chat.py')
        self.schemas = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.schemas)
        self.history = AsyncMock(return_value={'past_messages': [], 'session_id': 'session-of-b'})
        self.flow = AsyncMock(return_value={'response': 'ok', 'is_answered': True})
        self.endpoint = load_function('api/v1/routers/chat.py', 'chat_with_agent',
            Path=Path, Query=Query, Depends=Depends, BackgroundTasks=BackgroundTasks,
            ChatRequest=self.schemas.ChatRequest, Request=Request,
            get_api_key_or_session=lambda: {}, require_agent_permission=lambda *args: lambda: {},
            HTTPException=HTTPException, ModelConfigurationError=ModelConfigurationError,
            JSONResponse=JSONResponse, uuid=uuid, asyncio=asyncio,
            get_agent_with_visibility=AsyncMock(return_value=(object(), True, True, True)),
            apply_agent_answer_settings=lambda *args: {}, get_owner_email_by_agent_id=AsyncMock(return_value='owner'),
            enforce_query_cap=AsyncMock(),
            ensure_session_belongs_to_agent=self.guard, get_past_messages_safe=self.history,
            get_agent_runtime_db=AsyncMock(return_value=({'db_id': 'db'}, 0)),
            run_agent_flow=self.flow, _generate_follow_up_safe=AsyncMock(return_value=None),
            maybe_upload_csv_export=AsyncMock(return_value=None), persist_chat_logs=AsyncMock(),
            persist_health_event=AsyncMock(),
            build_chat_response=lambda result, body, session_id, *rest: {'session_id': session_id,
                                                                        'response': result['response']})

    async def ask(self, agent_id, session_id):
        body = self.schemas.ChatRequest(query='how many orders?', session_id=session_id)
        with patch.dict(sys.modules, {
                **session_module(get_session_details=session_store('agent-b')),
                'agent.utils.common_utils': types.SimpleNamespace(serialize_db_value=lambda value: value)}):
            return await self.endpoint(agent_id=agent_id, stream=False, body=body,
                                       auth={'auth_type': 'agent_api_key', 'agent_id': agent_id}, user={})

    async def test_foreign_session_is_refused_before_history_or_model(self):
        # The query-cap check before it only reads the owner's count; nothing is charged.
        with self.assertRaises(HTTPException) as caught:
            await self.ask('agent-a', 'session-of-b')
        self.assertEqual(caught.exception.status_code, 404)
        self.history.assert_not_awaited()
        self.flow.assert_not_awaited()

    async def test_unknown_session_is_refused(self):
        with self.assertRaises(HTTPException) as caught:
            await self.ask('agent-b', 'never-created')
        self.assertEqual(caught.exception.status_code, 404)
        self.flow.assert_not_awaited()

    async def test_own_session_continues(self):
        response = await self.ask('agent-b', 'session-of-b')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.body)['session_id'], 'session-of-b')
        self.history.assert_awaited_once()
        self.flow.assert_awaited_once()

    async def test_new_conversation_needs_no_session(self):
        for missing in (None, '', 'string'):
            with self.subTest(session_id=missing):
                response = await self.ask('agent-a', missing)
                self.assertEqual(response.status_code, 200)


RESULT = {'columns': [{'name': 'region', 'type': 'text'}, {'name': 'total', 'type': 'numeric'}],
          'rows': [{'region': 'North', 'total': 250.0}, {'region': 'row-only-region', 'total': 200.0}],
          'row_count': 2, 'truncated': False}


def stored_row(debug_info=None):
    return types.SimpleNamespace(chat_id='c1', user_query='totals by region?', gpt_response='North 250, South 200',
                                 refined_query='totals by region', sql_query=SQL, db_output=ROWS, feedback=None,
                                 created_at=datetime(2026, 10, 23), chart_output=None,
                                 debug_info={'sql_query': SQL, 'db_result': RESULT} if debug_info is None else debug_info,
                                 graph_output={'graph_suggestion': 'bar', 'graph_data': [{'label': 'North', 'value': 250}],
                                               'metadata': {}})


def replay_function(rows):
    @asynccontextmanager
    async def get_async_session():
        yield types.SimpleNamespace(execute=AsyncMock(return_value=types.SimpleNamespace(all=lambda: [(r,) for r in rows])))
    chart = load_function('session/db_utils/session_db_utils.py', '_chart_for_replay')
    return load_function('session/db_utils/session_db_utils.py', 'get_session_data',
                         get_async_session=get_async_session, select=MagicMock(), ChatLogs=MagicMock(),
                         Row=tuple, _chart_for_replay=chart)


class ReplayVisibilityTests(unittest.IsolatedAsyncioTestCase):
    """get_session_data serves only what the live answer would have shown."""

    async def replay(self, show_sql_query, show_db_result):
        return await replay_function([stored_row()])(
            's1', show_sql_query=show_sql_query, show_db_result=show_db_result)

    async def test_each_setting_controls_its_own_field(self):
        for show_sql, show_rows in ((True, True), (False, True), (True, False), (False, False)):
            with self.subTest(show_sql_query=show_sql, show_db_result=show_rows):
                user, assistant = await self.replay(show_sql, show_rows)
                debug = assistant['debug_info']
                self.assertEqual(debug['query'], 'totals by region?')
                self.assertEqual(debug['refine_query'], 'totals by region')
                self.assertEqual(debug.get('sql_query'), SQL if show_sql else None)
                self.assertEqual('sql_query' in debug, show_sql)
                self.assertEqual(debug.get('db_output'), ROWS if show_rows else None)
                self.assertEqual('db_output' in debug, show_rows)
                # The column-labelled block stored for the turn follows the rows setting.
                self.assertEqual(assistant['result'], RESULT if show_rows else None)
                self.assertNotIn('result', user)
                # Anything else on the turn is untouched by the settings.
                self.assertEqual(assistant['message'], 'North 250, South 200')
                self.assertEqual(assistant['graph_output']['chart_suggestion'], 'bar')
                self.assertEqual(user['message'], 'totals by region?')
                if not show_sql:
                    self.assertNotIn('SELECT', json.dumps([user, assistant]))
                if not show_rows:
                    self.assertNotIn('row-only-region', json.dumps([user, assistant]))

    async def test_turns_without_a_stored_block_replay_none(self):
        _, assistant = await replay_function([stored_row(debug_info={})])(
            's1', show_sql_query=True, show_db_result=True)
        self.assertIsNone(assistant['result'])
        self.assertEqual(assistant['debug_info']['db_output'], ROWS)

    async def test_callers_must_state_the_settings(self):
        with self.assertRaises(TypeError):
            await replay_function([stored_row()])('s1')

    def test_every_product_caller_passes_both_settings(self):
        """A gate on the call sites: no route can serve saved turns without the settings."""
        callers = []
        for path in BACKEND.rglob('*.py'):
            if 'tests' in path.parts:
                continue
            tree = ast.parse(path.read_bytes())
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    name = getattr(node.func, 'id', None) or getattr(node.func, 'attr', None)
                    if name == 'get_session_data':
                        callers.append((path.relative_to(BACKEND).as_posix(), {k.arg for k in node.keywords}))
        self.assertTrue(callers)
        for where, keywords in callers:
            with self.subTest(caller=where):
                self.assertLessEqual({'show_sql_query', 'show_db_result'}, keywords)


def visibility(flags_by_agent):
    async def get_agent_with_visibility(agent_id):
        if agent_id not in flags_by_agent:
            raise HTTPException(status_code=404, detail=f'Agent {agent_id} not found')
        show_sql, show_rows = flags_by_agent[agent_id]
        return object(), show_sql, show_rows, show_sql or show_rows
    return AsyncMock(side_effect=get_agent_with_visibility)


AGENTS = {'agent-visible': (True, True), 'agent-hidden': (False, False)}


def owned_by(agent):
    async def details(session_id, agent_id):
        return {'session_id': session_id, 'created_time': None, 'session_title': 't'} if agent_id == agent else None
    return details


class SavedConversationRouteTests(unittest.IsolatedAsyncioTestCase):
    """Allowed and denied behaviour on each route that serves saved turns."""

    async def assert_route(self, call, agent):
        payload = await call(agent)
        text = json.dumps(payload, default=str)
        if AGENTS[agent][0]:
            self.assertIn(SQL, text)
            self.assertIn('row-only-region', text)
        else:
            self.assertNotIn('SELECT', text)
            self.assertNotIn('row-only-region', text)
        self.assertIn('North 250, South 200', text)  # the answer itself is always served

    async def test_session_detail_route(self):
        async def call(agent):
            route = load_function('api/v1/routers/sessions.py', 'get_session',
                                  Path=Path, Request=Request, Depends=Depends, HTTPException=HTTPException,
                                  get_api_key_or_session=lambda: {}, require_agent_permission=lambda *a: lambda: {},
                                  get_session_details=AsyncMock(side_effect=owned_by(agent)),
                                  get_session_data=replay_function([stored_row()]),
                                  get_agent_with_visibility=visibility(AGENTS), datetime=datetime,
                                  traceback=MagicMock())
            return await route(agent_id=agent, session_id='s1', auth={'user_id': None}, user={})
        for agent in AGENTS:
            with self.subTest(agent=agent):
                await self.assert_route(call, agent)

    async def test_session_messages_route(self):
        async def call(agent):
            helper = load_function('api/v1/utils/chat_helper.py', 'get_session_messages_data',
                                   get_agent_with_visibility=visibility(AGENTS))
            with patch.dict(sys.modules, session_module(
                    get_session_details=AsyncMock(side_effect=owned_by(agent)),
                    get_session_data=replay_function([stored_row()]))):
                return await helper('s1', agent)
        for agent in AGENTS:
            with self.subTest(agent=agent):
                await self.assert_route(call, agent)

    async def test_unknown_agent_is_refused(self):
        helper = load_function('api/v1/utils/chat_helper.py', 'get_session_messages_data',
                               get_agent_with_visibility=visibility(AGENTS))
        with self.assertRaises(HTTPException) as caught:
            await helper('s1', 'agent-missing')
        self.assertEqual(caught.exception.status_code, 404)


class CsvExportVisibilityTests(unittest.IsolatedAsyncioTestCase):
    """The CSV export is the turn's rows: refused for an agent that hides them."""

    async def export(self, agent):
        presign = self.presign = AsyncMock(return_value='https://synthetic.example.test/export.csv')
        s3 = types.SimpleNamespace(build_export_s3_key=lambda *parts: '/'.join(parts),
                                   generate_export_presigned_url=presign,
                                   check_s3_object_exists=AsyncMock(return_value=True), CSV_EXPORT_URL_EXPIRY=900)
        route = load_function('api/v1/routers/chat.py', 'export_session_csv',
                              Path=Path, Query=Query, Depends=Depends, HTTPException=HTTPException,
                              JSONResponse=JSONResponse, get_api_key_or_session=lambda: {},
                              get_chat_log_for_export=AsyncMock(return_value=types.SimpleNamespace(
                                  agent_id=agent, chat_id='c1', sql_query=SQL)),
                              get_agent_with_visibility=visibility(AGENTS))
        parents = {n: types.ModuleType(n) for n in ('agent', 'agent.utils')}
        with patch.dict(sys.modules, {**parents, 'agent.utils.s3_export_utils': s3}):
            return await route(session_id="s1", chat_id="c1", auth={})

    async def test_visible_agent_gets_a_download_link(self):
        response = await self.export("agent-visible")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.body)['export_url'], 'https://synthetic.example.test/export.csv')

    async def test_hidden_agent_is_refused_before_a_link_is_signed(self):
        with self.assertRaises(HTTPException) as caught:
            await self.export('agent-hidden')
        self.assertEqual(caught.exception.status_code, 403)
        self.presign.assert_not_awaited()


if __name__ == '__main__':
    unittest.main(verbosity=2)
