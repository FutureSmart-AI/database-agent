"""A supplied session_id continues a conversation only on the agent that created it.

Chat history is read by session_id alone, so without this check a caller holding a key for
agent A could pass a session created on agent B and have B's questions and answers replayed
into A's model context (and appended to B's session). Synthetic boundaries; no external calls.
"""
import asyncio
import importlib.util
import json
import sys
import types
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from fastapi import BackgroundTasks, Depends, HTTPException, Path, Query
from fastapi.responses import JSONResponse
from starlette.requests import Request
from access_policy_harness import BACKEND, load_function

sys.path.insert(0, str(BACKEND))
from agent.utils.model_profiles import ModelConfigurationError


def session_store(owner_agent):
    """get_session_details as the product implements it: match on session AND agent."""
    async def get_session_details(session_id, agent_id):
        if session_id == 'session-of-b' and agent_id == owner_agent:
            return {'session_id': session_id, 'created_time': None, 'session_title': 't'}
        return None
    return types.SimpleNamespace(get_session_details=AsyncMock(side_effect=get_session_details))


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
            enforce_query_cap=AsyncMock(), ensure_session_belongs_to_agent=self.guard,
            get_past_messages_safe=self.history,
            get_agent_runtime_db=AsyncMock(return_value=({'db_id': 'db'}, 0)),
            run_agent_flow=self.flow, _generate_follow_up_safe=AsyncMock(return_value=None),
            maybe_upload_csv_export=AsyncMock(return_value=None), persist_chat_logs=AsyncMock(),
            persist_health_event=AsyncMock(),
            build_chat_response=lambda result, body, session_id, *rest: {'session_id': session_id,
                                                                        'response': result['response']})

    async def ask(self, agent_id, session_id):
        body = self.schemas.ChatRequest(query='how many orders?', session_id=session_id)
        with patch.dict(sys.modules, {
                'session': types.ModuleType('session'), 'session.db_utils': types.ModuleType('session.db_utils'),
                'session.db_utils.session_db_utils': session_store('agent-b'),
                'agent.utils.common_utils': types.SimpleNamespace(serialize_db_value=lambda value: value)}):
            return await self.endpoint(agent_id=agent_id, stream=False, body=body,
                                       auth={'auth_type': 'agent_api_key', 'agent_id': agent_id}, user={})

    async def test_foreign_session_is_refused_before_history_or_model(self):
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


class SavedResultReplayTests(unittest.IsolatedAsyncioTestCase):
    """GET .../sessions/{id} additively serves the column-labelled block stored per turn."""

    async def replay(self, debug_info):
        from contextlib import asynccontextmanager
        from datetime import datetime
        from unittest.mock import MagicMock
        row = types.SimpleNamespace(chat_id='c1', user_query='totals?', gpt_response='North 250', refined_query=None,
                                    sql_query='SELECT 1', db_output='[["North", 250]]', feedback=None,
                                    created_at=datetime(2026, 10, 23), debug_info=debug_info,
                                    chart_output=None, graph_output=None)

        @asynccontextmanager
        async def get_async_session():
            yield types.SimpleNamespace(execute=AsyncMock(return_value=types.SimpleNamespace(all=lambda: [(row,)])))

        chart = load_function('session/db_utils/session_db_utils.py', '_chart_for_replay')
        replay = load_function('session/db_utils/session_db_utils.py', 'get_session_data',
                               get_async_session=get_async_session, select=MagicMock(), ChatLogs=MagicMock(),
                               Row=tuple, _chart_for_replay=chart)
        return await replay('s1')

    async def test_stored_result_block_is_served_alongside_unchanged_fields(self):
        block = {'columns': [{'name': 'region', 'type': 'text'}], 'rows': [{'region': 'North'}],
                 'row_count': 1, 'truncated': False}
        user, assistant = await self.replay({'db_result': block, 'sql_query': 'SELECT 1'})
        self.assertEqual(assistant['result'], block)
        self.assertEqual(assistant['debug_info']['db_output'], '[["North", 250]]')
        self.assertNotIn('result', user)

    async def test_turns_without_a_stored_block_replay_none(self):
        _, assistant = await self.replay(None)
        self.assertIsNone(assistant['result'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
