"""Free sample-data questions: who is charged, what a visitor may reach, and the allowance.

The pure tests need nothing. The PostgreSQL tests run against a disposable database named by
DEMO_ALLOWANCE_TEST_URL (an asyncpg URL; CI starts one) and are skipped without it. They apply
the real migration, then check the limits, concurrent questions, the budget and the usage
measurements on actual SQL.
"""
import asyncio
import importlib.util
import os
import pathlib
import types
import unittest

for name, value in {
    "POSTGRES_USER": "unused", "POSTGRES_PASSWORD": "unused",
    "POSTGRES_HOST": "127.0.0.1", "POSTGRES_PORT": "5432", "POSTGRES_DB_NAME": "unused",
    "LANGCHAIN_TRACING_V2": "false", "LANGSMITH_TRACING": "false", "OTEL_EXPORTER_ENDPOINT": "",
}.items():
    os.environ.setdefault(name, value)

from chatbot_management.db_utils import demo_allowance as da
from agent.utils.authorization import demo_visitor_allowed

DEMO = types.SimpleNamespace(is_demo=True, owner_id="Demo-Owner@futuresmart.ai")
PLAIN = types.SimpleNamespace(is_demo=False, owner_id="someone@example.com")
TEST_URL = os.getenv("DEMO_ALLOWANCE_TEST_URL")
# Run from backend/ (CI) or the image's /app: the migrations sit under the working directory.
MIGRATIONS = [pathlib.Path.cwd() / f"migrations/versions/{name}.py"
              for name in ("add_demo_questions", "demo_audience_answer_reports")]


def session_auth(email, verified=True, claim_email=None, auth_type="session"):
    """What get_api_key_or_session returns for a signed-in user (auth service ID-token claims)."""
    return {"auth_type": auth_type, "user_id": email,
            "session_data": {"email": email, "all_claims": {
                "email": email if claim_email is None else claim_email,
                "email_verified": verified}}}


class WhoIsCharged(unittest.TestCase):
    def test_visitor_on_demo_agent_is_charged_lowercased(self):
        self.assertEqual(da.demo_question_user(DEMO, "session", "Visitor@Example.com"),
                         "visitor@example.com")

    def test_owner_and_ordinary_agents_are_not_demo_questions(self):
        self.assertIsNone(da.demo_question_user(DEMO, "session", "demo-owner@futuresmart.ai"))
        self.assertIsNone(da.demo_question_user(PLAIN, "session", "visitor@example.com"))
        self.assertIsNone(da.demo_question_user(DEMO, "master_api_key", None))

    def test_anonymous_non_owner_is_refused_not_free(self):
        self.assertEqual(da.demo_question_user(DEMO, "agent_api_key", None), "")


class InternalAccounts(unittest.TestCase):
    def test_verified_internal_domains_are_internal(self):
        for email in ("researcher@aidemos.com", "Pradip@FutureSmart.ai"):
            self.assertEqual(da.demo_audience(session_auth(email)), da.INTERNAL, email)
        self.assertEqual(da.demo_audience(session_auth("x@aidemos.com", verified="true")),
                         da.INTERNAL)

    def test_everything_else_is_public(self):
        cases = [
            session_auth("x@aidemos.com", verified=False),          # unverified
            session_auth("x@aidemos.com", verified=None),           # claim missing
            session_auth("x@aidemos.com", verified="false"),
            session_auth("x@sub.aidemos.com"),                       # subdomain
            session_auth("x@futuresmart.ai.example.com"),            # look-alike suffix
            session_auth("x@notfuturesmart.ai"),                     # partial string
            session_auth("x@example.com"),
            session_auth("x@aidemos.com", claim_email="y@example.com"),  # claims for someone else
            session_auth("@aidemos.com"),
            session_auth("x@aidemos.com", auth_type="master_api_key"),   # declared, not verified
            session_auth("x@aidemos.com", auth_type="agent_api_key"),
            None,
        ]
        for auth in cases:
            self.assertEqual(da.demo_audience(auth), da.PUBLIC, auth)


class VisitorRoutes(unittest.TestCase):
    def test_chat_surfaces_are_allowed(self):
        for path in ("/v1/agents/A/chat", "/v1/agents/A/sessions", "/v1/agents/A/sessions/S/messages",
                     "/v1/agents/A/feedback", "/v1/agents/A/reports", "/v1/agents/A",
                     "/v1/agents/A/databases",
                     "/v1/agents/A/databases/D/tables"):
            self.assertTrue(demo_visitor_allowed("use", path), path)
        self.assertTrue(demo_visitor_allowed("read", "/v1/agents/A/config", "GET"))

    def test_changes_and_cross_user_reports_are_refused(self):
        for permission, path in (("write", "/v1/agents/A"), ("write", "/v1/agents/A/config/params"),
                                 ("delete", "/v1/agents/A"), ("read", "/v1/agents/A/api-keys"),
                                 ("invite", "/v1/agents/A/invitations"),
                                 ("use", "/v1/agents/A/analytics/queries"),
                                 ("use", "/v1/agents/A/statistics"),
                                 ("use", "/v1/agents/A/databases/check")):
            self.assertFalse(demo_visitor_allowed(permission, path), (permission, path))
        self.assertFalse(demo_visitor_allowed("read", "/v1/agents/A/config", "POST"))


@unittest.skipUnless(TEST_URL, "DEMO_ALLOWANCE_TEST_URL not set")
class AllowanceOnPostgres(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

        self.text = text
        self.engine = create_async_engine(TEST_URL)
        self.Session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        async with self.engine.begin() as conn:
            for table in ("nl2sql_demo_questions", "nl2sql_agent_health_events",
                          "user_provider_keys", "chatbot_details", "nl2sql_answer_reports",
                          "nl2sql_logs"):
                await conn.execute(text(f"drop table if exists {table}"))
            await conn.execute(text(
                "create table user_provider_keys (owner_id text, created_at timestamptz)"))
            await conn.execute(text(
                "create table chatbot_details (owner_id text, is_demo boolean, deleted boolean,"
                " created_at timestamp)"))
            await conn.execute(text(
                "create table nl2sql_logs (id serial primary key, session_id text, user_id text,"
                " agent_id text, chat_id text, query text, refined_query text, sql_query text,"
                " db_output text, response text, graph_output json, chart_output json,"
                " is_answered boolean, feedback text, created_at timestamp)"))
            await conn.execute(text(
                "create table nl2sql_agent_health_events (chat_id text primary key, cost_usd float,"
                " total_tokens int, route text, status text, failure_category text,"
                " failed_stage text, rows_returned int, chart_generated boolean, latency_ms int,"
                " key_type text)"))
            await conn.run_sync(self._migrate)
        da.DAILY_LIMIT, da.TOTAL_LIMIT, da.MONTHLY_BUDGET_USD = 5, 20, 150.0

    @staticmethod
    def _migrate(sync_conn):
        from alembic.migration import MigrationContext
        from alembic.operations import Operations

        for path in MIGRATIONS:
            spec = importlib.util.spec_from_file_location(path.stem, path)
            migration = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(migration)
            with Operations.context(MigrationContext.configure(sync_conn)):
                migration.upgrade()

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def reserve(self, user, chat_id, audience=da.PUBLIC):
        async with self.Session() as s:
            return await da.reserve_demo_question(s, user_id=user, agent_id="DEMO",
                                                  chat_id=chat_id, request_id=None,
                                                  audience=audience)

    async def finish(self, chat_id, answered):
        async with self.Session() as s:
            await da.finish_demo_question(s, chat_id, answered=answered)

    async def sql(self, statement, **params):
        async with self.engine.begin() as conn:
            await conn.execute(self.text(statement), params)

    async def test_daily_limit_holds_under_concurrent_questions(self):
        results = await asyncio.gather(*(self.reserve("a@x.com", f"a{i}") for i in range(12)),
                                       return_exceptions=True)
        refused = [r for r in results if isinstance(r, da.DemoRefusal)]
        self.assertEqual(len(results) - len(refused), 5)
        self.assertEqual({r.reason for r in refused}, {"daily"})
        self.assertIsNotNone(refused[0].status["daily_resets_at"])

    async def test_another_user_has_their_own_allowance(self):
        for i in range(5):
            await self.reserve("a@x.com", f"a{i}")
        with self.assertRaises(da.DemoRefusal):
            await self.reserve("a@x.com", "a5")
        status = await self.reserve("b@x.com", "b0")
        self.assertEqual((status["daily_used"], status["daily_remaining"]), (1, 4))

    async def test_failed_questions_are_not_charged_but_answered_are(self):
        for i in range(5):
            await self.reserve("a@x.com", f"a{i}")
            await self.finish(f"a{i}", answered=(i == 0))
        status = await self.reserve("a@x.com", "a5")
        self.assertEqual(status["daily_used"], 2)

    async def test_lifetime_limit_counts_older_days(self):
        await self.sql("insert into nl2sql_demo_questions (chat_id, user_id, agent_id, status, created_at)"
                       " select 'old' || g, 'a@x.com', 'DEMO', 'answered',"
                       " (now() at time zone 'utc') - interval '3 days' from generate_series(1, 20) g")
        with self.assertRaises(da.DemoRefusal) as refused:
            await self.reserve("a@x.com", "new")
        self.assertEqual(refused.exception.reason, "total")
        self.assertIn("own OpenAI key", refused.exception.message)

    async def test_budget_counts_recorded_cost_and_unpriced_questions(self):
        da.MONTHLY_BUDGET_USD = 0.20
        await self.reserve("a@x.com", "p1")
        await self.sql("insert into nl2sql_agent_health_events (chat_id, cost_usd, total_tokens) values ('p1', 0.05, 9000)")
        await self.reserve("b@x.com", "p2")   # unpriced: counts 0.07 -> 0.12 spent
        await self.reserve("c@x.com", "p3")   # 0.12 + 0.07 = 0.19 <= 0.20 before this one
        with self.assertRaises(da.DemoRefusal) as refused:
            await self.reserve("d@x.com", "p4")
        self.assertEqual(refused.exception.reason, "budget")
        self.assertNotIn("_month_spend_usd", refused.exception.status)

    async def test_usage_summary(self):
        await self.sql("insert into nl2sql_demo_questions (chat_id, user_id, agent_id, status, created_at) values"
                       " ('u1', 'a@x.com', 'DEMO', 'answered', (now() at time zone 'utc') - interval '2 days'),"
                       " ('u2', 'a@x.com', 'DEMO', 'answered', (now() at time zone 'utc') - interval '1 hour'),"
                       " ('u3', 'a@x.com', 'DEMO', 'answered', (now() at time zone 'utc')),"
                       " ('u4', 'b@x.com', 'DEMO', 'failed', (now() at time zone 'utc')),"
                       " ('u5', 'c@x.com', 'DEMO', 'answered', (now() at time zone 'utc'))")
        await self.sql("insert into nl2sql_agent_health_events (chat_id, cost_usd, total_tokens) values ('u1', 0.02, 5000), ('u2', 0.03, 7000)")
        await self.sql("insert into user_provider_keys values ('A@x.com', now())")
        await self.sql("insert into chatbot_details values ('c@x.com', false, false, now() + interval '1 minute')")
        async with self.Session() as s:
            summary = (await da.demo_usage_summary(s))["public"]
        self.assertEqual(summary["users"], {"first_question": 2, "explored_3": 1, "returning": 1,
                                            "converted_key": 1, "converted_agent": 1})
        self.assertEqual(summary["questions"]["questions"], 5)
        self.assertEqual(summary["questions"]["failed"], 1)
        self.assertAlmostEqual(summary["questions"]["recorded_cost_usd"], 0.05)
        self.assertEqual(summary["questions"]["unpriced"], 3)
        self.assertEqual(summary["questions"]["tokens"], 12000)
        self.assertEqual(summary["questions"]["priced_by_langsmith"], 2)

    async def test_unpriced_question_with_tokens_counts_at_the_blended_rate(self):
        """Hosted runs carry tokens but no LangSmith cost: they must count at the rate the
        Usage screen uses, not at the in-flight estimate and never as free."""
        from chatbot_management.utils.usage_limits import TOKEN_RATE_USD
        await self.reserve("a@x.com", "t1")
        await self.sql("insert into nl2sql_agent_health_events (chat_id, cost_usd, total_tokens) values ('t1', null, 10000)")
        await self.reserve("b@x.com", "t2")   # in flight: no event yet
        async with self.Session() as s:
            summary = await da.demo_usage_summary(s)
        q = summary["public"]["questions"]
        self.assertEqual((q["priced_from_tokens"], q["unpriced"]), (1, 1))
        self.assertAlmostEqual(q["spend_usd"], 10000 * TOKEN_RATE_USD + da.UNPRICED_COST_USD)

    async def test_internal_user_is_never_refused_and_is_recorded(self):
        await self.sql("insert into nl2sql_demo_questions (chat_id, user_id, agent_id, status, created_at, audience)"
                       " select 'old' || g, 'r@aidemos.com', 'DEMO', 'answered',"
                       " (now() at time zone 'utc') - interval '3 days', 'internal' from generate_series(1, 25) g")
        for i in range(8):   # past both the daily (5) and lifetime (20) limits set for the tests
            status = await self.reserve("r@aidemos.com", f"r{i}", da.INTERNAL)
        self.assertTrue(status["unlimited"])
        self.assertEqual((status["daily_used"], status["total_used"]), (8, 33))
        self.assertIsNone(status["daily_remaining"])

    async def test_internal_usage_is_outside_the_public_budget_and_reported_apart(self):
        da.MONTHLY_BUDGET_USD = 0.10
        await self.reserve("r@aidemos.com", "i1", da.INTERNAL)
        await self.sql("insert into nl2sql_agent_health_events (chat_id, cost_usd, total_tokens)"
                       " values ('i1', 5.00, 900000)")
        await self.reserve("r@aidemos.com", "i2", da.INTERNAL)   # in flight, still allowed
        status = await self.reserve("a@x.com", "p1")              # $5 internal does not close it
        self.assertTrue(status["budget_open"])
        with self.assertRaises(da.DemoRefusal) as refused:      # 0.07 + 0.07 > 0.10
            await self.reserve("b@x.com", "p2")
        self.assertEqual(refused.exception.reason, "budget")
        await self.reserve("r@aidemos.com", "i3", da.INTERNAL)   # public budget does not stop them
        async with self.Session() as s:
            summary = await da.demo_usage_summary(s)
        self.assertEqual(summary["internal"]["questions"]["questions"], 3)
        self.assertEqual(summary["internal"]["users"]["first_question"], 1)
        self.assertAlmostEqual(summary["internal"]["questions"]["recorded_cost_usd"], 5.00)
        self.assertEqual(summary["public"]["questions"]["questions"], 1)
        self.assertAlmostEqual(summary["public"]["questions"]["month_spend_usd"], da.UNPRICED_COST_USD)
        self.assertEqual(summary["limits"]["budget_applies_to"], "public")

    async def test_audience_column_rejects_unknown_values(self):
        with self.assertRaises(Exception):
            await self.sql("insert into nl2sql_demo_questions (chat_id, user_id, agent_id, audience)"
                           " values ('z', 'a@x.com', 'DEMO', 'staff')")

    async def add_turn(self, chat_id, user, query, rows="[[1]]", minutes=0):
        await self.sql("insert into nl2sql_logs (session_id, user_id, agent_id, chat_id, query,"
                       " refined_query, sql_query, db_output, response, is_answered, created_at)"
                       " values ('S1', :user, 'DEMO', :chat_id, :query, :query, 'select 1', :rows,"
                       " 'answer to ' || :query, true,"
                       " (now() at time zone 'utc') - make_interval(mins => :ago))",
                       user=user, chat_id=chat_id, query=query, rows=rows, ago=10 - minutes)

    async def test_answer_report_snapshots_the_conversation_up_to_the_answer(self):
        from chatbot_management.db_utils import answer_reports as ar
        await self.add_turn("c1", "r@aidemos.com", "Top five customers by spend", minutes=1)
        await self.add_turn("c2", "r@aidemos.com", "Only show the top two",
                            rows='[["Lucas Thompson", 9953.07], ["Diego Hill", 8596.4]]', minutes=2)
        await self.add_turn("c3", "r@aidemos.com", "Something later", minutes=3)
        await self.sql("insert into nl2sql_agent_health_events (chat_id, total_tokens, route,"
                       " chart_generated) values ('c2', 7000, 'sql', false)")
        async with self.Session() as s:
            report = await ar.create_report(s, agent_id="DEMO", session_id="S1", chat_id="c2",
                                            user_id="R@aidemos.com", category="wrong_chart",
                                            note="The chart disappeared", expected="Two bars")
        self.assertRegex(report["report_id"], r"^RPT_[0-9A-F]{8}$")
        async with self.Session() as s:
            listed = await ar.list_reports(s, agent_id="DEMO")
        self.assertEqual(listed["total"], 1)
        snap = listed["reports"][0]["snapshot"]
        self.assertEqual([t["question"] for t in snap["turns"]],
                         ["Top five customers by spend", "Only show the top two"])
        self.assertEqual((snap["reported_turn"], snap["turns"][1]["row_count"]), (2, 2))
        self.assertEqual(snap["run"]["chart_generated"], False)
        self.assertEqual(listed["reports"][0]["user_id"], "r@aidemos.com")
        async with self.Session() as s:
            self.assertTrue(await ar.set_report_status(s, report["report_id"], "triaged"))
        async with self.Session() as s:
            self.assertEqual((await ar.list_reports(s, status="triaged"))["total"], 1)

    async def test_only_the_asker_can_report_and_input_is_checked(self):
        from chatbot_management.db_utils import answer_reports as ar
        await self.add_turn("c1", "a@x.com", "Top five customers by spend")
        cases = [
            (dict(user_id="b@x.com", category="wrong_answer", note="x", chat_id="c1"), 403),
            (dict(user_id="a@x.com", category="wrong_answer", note="x", chat_id="nope"), 404),
            (dict(user_id="a@x.com", category="bogus", note="x", chat_id="c1"), 400),
            (dict(user_id="a@x.com", category="wrong_answer", note="  ", chat_id="c1"), 400),
            (dict(user_id="", category="wrong_answer", note="x", chat_id="c1"), 401),
        ]
        for kwargs, status in cases:
            async with self.Session() as s:
                with self.assertRaises(ar.ReportError) as raised:
                    await ar.create_report(s, agent_id="DEMO", session_id="S1", expected=None,
                                           **kwargs)
            self.assertEqual(raised.exception.status, status, kwargs)
        async with self.Session() as s:
            self.assertEqual((await ar.list_reports(s))["total"], 0)


if __name__ == "__main__":
    unittest.main()
