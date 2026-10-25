"""Regression test for Tables & visibility enforcement. No database, no LLM, no keys.

    python tests/backend/test_table_access_guard.py

Covers the two ways QA got an excluded table read anyway (round 1, S60 and S62): a
direct SELECT against it, and a JOIN through it to reach another table's rows. Both
must be stopped before the query is sent to the database, with the SQL and rows
cleared from state so nothing reaches the caller.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2] / "backend"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# prompts.py -> sqlmodel_session raises at import when these are unset. This test never
# opens a connection; the values only have to exist.
for _var, _val in {
    "POSTGRES_USER": "unused", "POSTGRES_PASSWORD": "unused",
    "POSTGRES_HOST": "localhost", "POSTGRES_PORT": "5432",
    "POSTGRES_DB_NAME": "unused",
}.items():
    os.environ.setdefault(_var, _val)

import agent.nodes.sql_exec as sql_exec_mod
import agent.utils.table_access as table_access
from agent.nodes.check_pandas import check_pandas_needed
from agent.utils.table_access import blocked_tables

PERMITTED = ["orders", "order_items", "products", "subscriptions", "action_log"]
EXCLUDED = ["customers", "returns"]

failures: list[str] = []


def check(label: str, got, want) -> None:
    if got == want:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}\n          want={want!r}\n          got ={got!r}")
        failures.append(label)


def test_sql_parsing() -> None:
    print("\nWhich tables does a query read?")
    cases = [
        ("direct read of an excluded table",
         "SELECT COUNT(*) FROM returns WHERE status::text ILIKE '%pending%'", ["returns"]),
        ("excluded table reached through a join",
         "SELECT t1.plan FROM subscriptions AS t1 JOIN customers AS t2 "
         "ON t1.customer_id = t2.id WHERE t2.name = 'A'", ["customers"]),
        ("schema-qualified",
         "SELECT * FROM public.customers c JOIN public.orders o ON o.customer_id = c.id",
         ["customers"]),
        ("quoted identifier", 'SELECT * FROM "customers"', ["customers"]),
        ("inside a subquery",
         "SELECT id FROM orders WHERE customer_id IN (SELECT id FROM customers)", ["customers"]),
        ("inside a CTE body",
         "WITH recent AS (SELECT * FROM customers) SELECT COUNT(*) FROM recent", ["customers"]),
        ("CTE alias that merely shares an excluded table's name",
         "WITH customers AS (SELECT 1 AS x) SELECT * FROM customers", []),
        ("second statement after a semicolon",
         "SELECT 1 FROM orders; SELECT 2 FROM customers", ["customers"]),
        ("permitted tables only",
         "SELECT COUNT(*) FROM orders WHERE placed_at >= '2026-08-01'", []),
        ("server metadata is not customer data",
         "SELECT column_name FROM information_schema.columns WHERE table_name='customers'", []),
    ]
    for label, sql, want in cases:
        check(label, blocked_tables(sql, PERMITTED, EXCLUDED, "postgresql") or [], want)

    print("\nWhen the answer isn't knowable")
    broken = "SELECT ((( FROM customers WHERE"
    check("unparseable SQL + exclusions configured -> blocked",
          blocked_tables(broken, PERMITTED, EXCLUDED, "postgresql"), sorted(EXCLUDED))
    check("unparseable SQL + verified all-included map -> blocked",
          blocked_tables(broken, PERMITTED, [], "postgresql"), ["<unverifiable table references>"])
    check("unknown table in an all-included map -> blocked",
          blocked_tables("SELECT * FROM customers", PERMITTED, [], "postgresql"), ["customers"])
    check("explicitly permitted table with no exclusions -> allowed",
          blocked_tables("SELECT * FROM orders", PERMITTED, [], "postgresql"), None)


async def test_node_guard() -> None:
    print("\nsql_exec stops the query before the database sees it")

    reached_db = []

    def tripwire(*_a, **_k):
        reached_db.append(True)
        return False, None, "should not have been called"

    async def fake_visibility(_user_id, _agent_id, _db_id):
        return list(PERMITTED), list(EXCLUDED)

    original_exec, original_vis = sql_exec_mod.try_exec_sql, table_access.get_table_visibility
    sql_exec_mod.try_exec_sql = tripwire
    table_access.get_table_visibility = fake_visibility
    try:
        state = {
            "user_id": "u", "agent_id": "a", "db_id": "db", "request_id": "r", "session_id": "s",
            "runtime_db_details": {"db_id": "db", "db_engine": "postgresql"},
            "selected_tables": ["subscriptions"],
            "sql_query": "SELECT t1.plan FROM subscriptions AS t1 "
                         "JOIN customers AS t2 ON t1.customer_id = t2.id",
        }
        # Nodes mutate their request state. Preserve the input for the separate
        # permitted request below; a denied request must remain terminal.
        out = await sql_exec_mod.node_sql_exec(dict(state))

        check("query never reached the database", reached_db, [])
        check("blocked tables recorded", out.get("access_denied_tables"), ["customers"])
        check("SQL cleared from state", out.get("sql_query"), "")
        check("rows cleared from state", out.get("db_result"), [])
        check("columns cleared from state", out.get("db_columns"), None)
        check("no sql_error, so no pointless sql_gen retry", out.get("sql_error"), None)
        check("routes straight to the answer", await check_pandas_needed(out), "final_answer_node")

        reached_db.clear()
        allowed_state = dict(state, sql_query="SELECT COUNT(*) FROM orders")
        await sql_exec_mod.node_sql_exec(allowed_state)
        check("a permitted query is still executed", reached_db, [True])
    finally:
        sql_exec_mod.try_exec_sql = original_exec
        table_access.get_table_visibility = original_vis


def main() -> int:
    test_sql_parsing()
    asyncio.run(test_node_guard())
    print()
    if failures:
        print(f"{len(failures)} check(s) FAILED: {', '.join(failures)}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
