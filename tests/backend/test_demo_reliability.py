"""Sample-data reliability fixes: descriptions written while a description job runs are kept,
the dashboard's table count, and what the answer and router prompts are given.

The pure tests need nothing. The PostgreSQL test runs against the disposable database named by
DEMO_ALLOWANCE_TEST_URL (CI starts one) and is skipped without it.
"""
import os
import unittest

for name, value in {
    "POSTGRES_USER": "unused", "POSTGRES_PASSWORD": "unused",
    "POSTGRES_HOST": "127.0.0.1", "POSTGRES_PORT": "5432", "POSTGRES_DB_NAME": "unused",
    "LANGCHAIN_TRACING_V2": "false", "LANGSMITH_TRACING": "false", "OTEL_EXPORTER_ENDPOINT": "",
}.items():
    os.environ.setdefault(name, value)

from knowledge.db_utils import table_description_db_utils as tdu

TEST_URL = os.getenv("DEMO_ALLOWANCE_TEST_URL")


class DescriptionJobMerge(unittest.TestCase):
    def test_description_written_while_the_job_ran_is_kept(self):
        started = {"orders": "", "payments": "auto: payments"}
        stored_now = [{"orders": "Revenue is captured payments, in US dollars."},
                      {"payments": "auto: payments"}]
        generated = {"orders": "Each row is an order.", "payments": "Each row is a payment."}
        description, flags = tdu.merge_generated_descriptions(
            stored_now, {"orders": True, "payments": False}, started, generated,
            ["orders", "payments", "returns"])
        self.assertEqual(description, [
            {"orders": "Revenue is captured payments, in US dollars."},  # written meanwhile: kept
            {"payments": "Each row is a payment."},                        # unchanged: job fills it
            {"returns": ""},                                               # nothing anywhere
        ])
        self.assertEqual(flags, {"orders": True, "payments": False, "returns": True})

    def test_a_cleared_description_is_also_a_write_that_wins(self):
        description, _ = tdu.merge_generated_descriptions(
            [{"orders": ""}], {}, {"orders": "old"}, {"orders": "generated"}, ["orders"])
        self.assertEqual(description, [{"orders": ""}])

    def test_job_fills_blanks_and_reads_json_records(self):
        description, _ = tdu.merge_generated_descriptions(
            '[{"orders": ""}]', {}, {"orders": ""}, {"orders": "generated"}, ["orders"])
        self.assertEqual(description, [{"orders": "generated"}])


class TableCount(unittest.TestCase):
    def test_counts_only_tables_the_agent_may_read(self):
        from api.v1.utils.databases_helper import included_table_count
        self.assertEqual(included_table_count({"a": True, "b": False, "c": 1}), 2)
        self.assertEqual(included_table_count('{"a": true, "b": true}'), 2)

    def test_unknown_is_not_a_count(self):
        from api.v1.utils.databases_helper import included_table_count
        for flags in (None, {}, "not json", {"a": "yes"}):
            self.assertIsNone(included_table_count(flags), flags)


class AnswerSeesDefinitions(unittest.TestCase):
    def test_definitions_of_the_tables_read(self):
        from agent.nodes.final_answer import table_definitions_for_answer
        text = table_definitions_for_answer(
            {"public.orders": "Amounts are US dollars.", "customers": "One row per customer.",
             "returns": "Return requests."},
            ["orders", "customers"])
        self.assertIn("orders: Amounts are US dollars.", text)
        self.assertIn("customers: One row per customer.", text)
        self.assertNotIn("Return requests", text)
        self.assertEqual(table_definitions_for_answer({}, ["orders"]), "None provided.")

    def test_answer_prompt_carries_them(self):
        from agent.utils.prompts import get_answer_prompt
        prompt = get_answer_prompt("orders")
        rendered = prompt.format(refined_query="q", query="select 1", result="[]", user_info="",
                                 db_columns="total", table_definitions="- orders: US dollars")
        self.assertIn("- orders: US dollars", rendered)
        self.assertIn("never say", rendered)
        # Callers that do not pass definitions still render.
        self.assertIn("None provided.", prompt.format(refined_query="q", query="", result="[]",
                                                      user_info="", db_columns=""))


class FollowUpKeepsTheChart(unittest.TestCase):
    def system(self, **kwargs):
        from agent.utils.prompts import get_router_prompt
        return get_router_prompt(**kwargs).messages[0].prompt.template

    def test_follow_up_rule_only_with_history_and_charts(self):
        self.assertIn("Chart inheritance", self.system(supported_graphs="bar", has_history=True))
        self.assertNotIn("Chart inheritance", self.system(supported_graphs="bar", has_history=False))
        self.assertNotIn("Chart inheritance", self.system(supported_graphs="", has_history=True))


class ChartAgentGetsTheInheritedRequest(unittest.TestCase):
    """The chart agent reads the user's words; a narrowing follow-up has none about charts."""

    def question(self, previous_had_chart, **state):
        from agent.nodes.graph_agent_bridge import chart_follow_up_question
        base = {"query": "Only show the top two.", "past_messages": [{"role": "user", "content": "x"}],
                "visualization_query": "Bar chart of the top two customers by total spend"}
        return chart_follow_up_question({**base, **state}, previous_had_chart)

    def test_follow_up_to_a_charted_answer_keeps_the_chart(self):
        self.assertEqual(self.question(True), "Bar chart of the top two customers by total spend")

    def test_every_other_turn_keeps_the_users_words(self):
        self.assertIsNone(self.question(False))                              # no chart before
        self.assertIsNone(self.question(True, visualization_query=""))       # router: no chart now
        self.assertIsNone(self.question(True, past_messages=[]))             # first turn
        self.assertIsNone(self.question(True, query="Now as a pie chart"))   # user said it


class DemoVisitorFeedback(unittest.IsolatedAsyncioTestCase):
    """Hosted 2026-10-23: a visitor's thumbs-down rewrote their answer's stored SQL with the
    `generated_query` they sent ("x")."""

    async def feedback(self, visitor, asked=True):
        import sys
        import types
        from unittest.mock import AsyncMock, patch
        from api.v1.utils import feedback_helper as fh

        add, example = AsyncMock(), AsyncMock(side_effect=RuntimeError("no few-shot store in tests"))
        body = types.SimpleNamespace(session_id="S", chat_id="C", user_query="q", generated_query="x",
                                     label="incorrect", corrected_query="select 2")
        with patch.object(fh, "verify_agent_exists", AsyncMock()), \
                patch.object(fh, "_demo_visitor", AsyncMock(return_value=visitor)), \
                patch.object(fh, "_asked_by", AsyncMock(return_value=asked)), \
                patch.dict(sys.modules, {
                    "session.db_utils.session_db_utils": types.SimpleNamespace(add_user_feedback=add),
                    "knowledge.utils.few_shot_utils": types.SimpleNamespace(
                        get_few_shot_service=AsyncMock(return_value=types.SimpleNamespace(add_example=example)))}):
            await fh.process_feedback("A", body, auth={"auth_type": "session"})
        return add.await_args.kwargs, example

    async def test_visitor_feedback_records_the_verdict_only(self):
        stored, example = await self.feedback("visitor@example.com")
        self.assertEqual((stored["feedback"], stored["corrected_sql"]), ("rejected", None))
        example.assert_not_awaited()

    async def test_visitor_cannot_rate_someone_elses_answer(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as refused:
            await self.feedback("visitor@example.com", asked=False)
        self.assertEqual(refused.exception.status_code, 403)

    async def test_ordinary_agent_feedback_is_unchanged(self):
        stored, example = await self.feedback(None)
        self.assertEqual(stored["corrected_sql"], "select 2")
        example.assert_awaited()


@unittest.skipUnless(TEST_URL, "DEMO_ALLOWANCE_TEST_URL not set")
class DescriptionJobOnPostgres(unittest.IsolatedAsyncioTestCase):
    """The real save path: a description posted after the job read the record survives it."""

    async def asyncSetUp(self):
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from models.sql_models import TableDescription

        self.engine = create_async_engine(TEST_URL)
        Session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        async with self.engine.begin() as conn:
            await conn.execute(text(f"drop table if exists {TableDescription.__tablename__}"))
            await conn.run_sync(lambda c: TableDescription.__table__.create(c))

        async def sessions():
            async with Session() as session:
                yield session

        self.original = tdu.get_async_session
        tdu.get_async_session = sessions

    async def asyncTearDown(self):
        tdu.get_async_session = self.original
        await self.engine.dispose()

    async def stored(self):
        result = await tdu.list_table_description_from_db(None, "AG", db_id="DB")
        record = result["record"]
        return tdu._description_map(record.description), record.entry_flags

    async def test_definitions_posted_during_the_job_survive_it(self):
        ok = await tdu.upload_to_db_table_description(
            None, "AG", "", "", [{"orders": ""}, {"returns": ""}],
            {"orders": True, "returns": True}, db_id="DB")
        self.assertTrue(ok["status"])
        started, _ = await self.stored()                       # the job reads the record...
        await tdu.upload_to_db_table_description(              # ...provisioning posts definitions
            None, "AG", "", "", [{"orders": "Revenue is captured payments, in US dollars."},
                                 {"returns": ""}],
            {"orders": True, "returns": False}, db_id="DB")
        saved = await tdu.save_generated_table_descriptions(   # ...then the job saves
            "AG", "DB", started, {"orders": "generated", "returns": "generated r"},
            ["orders", "returns"])
        self.assertTrue(saved["status"], saved)
        descriptions, flags = await self.stored()
        self.assertEqual(descriptions, {"orders": "Revenue is captured payments, in US dollars.",
                                        "returns": "generated r"})
        self.assertEqual(flags, {"orders": True, "returns": False})


if __name__ == "__main__":
    unittest.main()
