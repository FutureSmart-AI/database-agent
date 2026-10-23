"""Session isolation on actual SQL: the product's queries against real PostgreSQL tables.

Runs against the disposable database named by SESSION_STORAGE_TEST_URL (an asyncpg URL; the
session-storage CI job starts one) and is skipped without it. The tables are the product's own
models (chat_sessions, nl2sql_logs); the functions are the product's source bodies, bound to
that database. Synthetic agents, sessions and rows only.

Covers the case the mocked tests cannot: a session id shared by two agents — the platform chat
service sends its own thread id to every agent it calls — must neither be refused nor replay
the other agent's turns.
"""
import os
import types
import unittest
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from unittest.mock import patch
import sys

from fastapi import HTTPException
from access_policy_harness import BACKEND, load_function

sys.path.insert(0, str(BACKEND))
TEST_URL = os.getenv("SESSION_STORAGE_TEST_URL")


@unittest.skipUnless(TEST_URL, "SESSION_STORAGE_TEST_URL not set")
class SessionStorageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy.engine.row import Row
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlmodel import select
        from models.sql_models import ChatLogs, ChatSessions

        from sqlalchemy import text

        # A schema of its own: the shared CI database may already hold older shapes of these
        # tables (created by other suites), which create_all would silently keep.
        run = uuid.uuid4().hex[:8]
        self.schema = f"session_storage_{run}"
        boot = create_async_engine(TEST_URL)
        async with boot.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        await boot.dispose()
        self.engine = create_async_engine(TEST_URL, connect_args={"server_settings": {"search_path": self.schema}})
        async with self.engine.begin() as conn:
            await conn.run_sync(lambda c: ChatSessions.metadata.create_all(
                c, tables=[ChatSessions.__table__, ChatLogs.__table__]))
        factory = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)

        @asynccontextmanager
        async def session_cm():
            async with factory() as s:
                yield s

        async def session_gen():
            async with factory() as s:
                yield s

        self.a, self.b = f"NL2SQL_A_{run}", f"NL2SQL_B_{run}"
        self.created_on_b = f"created-on-b-{run}"      # a session this API created for agent B
        self.thread = f"chat-service-thread-{run}"     # an id only the chat service knows
        t0 = datetime(2026, 10, 23, 12, 0)
        async with factory() as s:
            s.add(ChatSessions(session_id=self.created_on_b, chatbot_id=self.b, agent_id=self.b,
                               user_id="b-user", session_title="b", created_time=t0))
            for i, (session_id, agent, question) in enumerate([
                    (self.created_on_b, self.b, "B private question"),
                    (self.thread, self.b, "B turn in shared thread"),
                    (self.thread, self.a, "A turn in shared thread")]):
                s.add(ChatLogs(session_id=session_id, agent_id=agent, chat_id=f"{run}-{i}", user_id="u",
                               user_query=question, gpt_response=f"answer to {question}",
                               sql_query=f"SELECT '{agent}'", db_output=f'[["{agent}-row"]]',
                               created_at=t0 + timedelta(minutes=i)))
            await s.commit()

        common = dict(select=select, ChatLogs=ChatLogs, ChatSessions=ChatSessions, Row=Row)
        self.owners = load_function("session/db_utils/session_db_utils.py", "get_session_agent_ids",
                                    get_async_session=session_cm, **common)
        self.details = load_function("session/db_utils/session_db_utils.py", "get_session_details",
                                     get_async_session=session_cm, **common)
        chart = load_function("session/db_utils/session_db_utils.py", "_chart_for_replay")
        self.replay = load_function("session/db_utils/session_db_utils.py", "get_session_data",
                                    get_async_session=session_cm, _chart_for_replay=chart, **common)
        self.past = load_function("api/v1/utils/chat_helper.py", "get_past_conversation_safe",
                                  get_async_session=session_gen, **common)
        self.guard = load_function("api/v1/utils/chat_helper.py", "ensure_session_belongs_to_agent",
                                   HTTPException=HTTPException)
        self.export_row = load_function("api/v1/utils/chat_helper.py", "get_chat_log_for_export",
                                        get_async_session=session_gen, **common)
        self.feedback = load_function("session/db_utils/session_db_utils.py", "add_user_feedback",
                                      get_async_session=session_cm, **common)

    async def asyncTearDown(self):
        from sqlalchemy import text
        async with self.engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
        await self.engine.dispose()

    async def guarded(self, session_id, agent_id):
        stub = {"session": types.ModuleType("session"), "session.db_utils": types.ModuleType("session.db_utils"),
                "session.db_utils.session_db_utils": types.SimpleNamespace(get_session_agent_ids=self.owners)}
        with patch.dict(sys.modules, stub):
            await self.guard(session_id, agent_id)

    async def test_another_agents_session_is_refused(self):
        with self.assertRaises(HTTPException) as caught:
            await self.guarded(self.created_on_b, self.a)
        self.assertEqual(caught.exception.status_code, 404)
        self.assertIsNone(await self.details(self.created_on_b, self.a))

    async def test_own_new_and_chat_service_sessions_continue(self):
        for session_id, agent in ((self.created_on_b, self.b), (self.thread, self.a), (self.thread, self.b),
                                  (f"never-seen-{uuid.uuid4()}", self.a), (None, self.a)):
            with self.subTest(session=session_id, agent=agent):
                await self.guarded(session_id, agent)

    async def test_history_is_this_agents_turns_only(self):
        a_in_thread = await self.past(self.thread, self.a)
        self.assertEqual([m["content"] for m in a_in_thread],
                         ["A turn in shared thread", "answer to A turn in shared thread"])
        self.assertEqual(await self.past(self.created_on_b, self.a), [])
        self.assertEqual([m["content"] for m in await self.past(self.created_on_b, self.b)][0], "B private question")

    async def test_replay_is_this_agents_turns_only(self):
        turns = await self.replay(self.thread, agent_id=self.a, show_sql_query=True, show_db_result=True)
        self.assertEqual([t["message"] for t in turns if t["role"] == "user"], ["A turn in shared thread"])
        self.assertNotIn(self.b, repr(turns))
        hidden = await self.replay(self.thread, agent_id=self.a, show_sql_query=False, show_db_result=False)
        self.assertNotIn("SELECT", repr(hidden))
        self.assertNotIn(f"{self.a}-row", repr(hidden))

    async def test_export_lookup_is_scoped_to_the_key_agent(self):
        latest_for_a = await self.export_row(self.thread, None, agent_id=self.a)
        self.assertEqual(latest_for_a.agent_id, self.a)
        b_turn = (await self.export_row(self.thread, None, agent_id=self.b)).chat_id
        self.assertIsNone(await self.export_row(self.thread, b_turn, agent_id=self.a))
        self.assertEqual((await self.export_row(self.thread, b_turn)).agent_id, self.b)  # master key: unscoped

    async def test_feedback_reaches_only_this_agents_turns(self):
        b_turn = (await self.export_row(self.created_on_b, None, agent_id=self.b)).chat_id
        await self.feedback(self.created_on_b, b_turn, "rejected", "SELECT 'rewritten by A'", agent_id=self.a)
        unchanged = await self.export_row(self.created_on_b, b_turn)
        self.assertEqual((unchanged.feedback, unchanged.sql_query), (None, f"SELECT '{self.b}'"))
        await self.feedback(self.created_on_b, b_turn, "accepted", None, agent_id=self.b)
        self.assertEqual((await self.export_row(self.created_on_b, b_turn)).feedback, "accepted")


if __name__ == "__main__":
    unittest.main(verbosity=2)
