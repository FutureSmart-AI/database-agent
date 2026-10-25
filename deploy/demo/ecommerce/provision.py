"""Provision the Cedar Lane sample database and its shared demo agent.

Two steps, each safe to read before running. Nothing is printed that is a secret.

    python provision.py database [--replace]
        Creates the `sample_ecommerce` database on the server named by DEMO_ADMIN_DSN, loads
        the generated rows, and creates the SELECT-only role `sample_ecommerce_reader`
        (password: DEMO_READER_PASSWORD). Then, connected AS that role, it checks every
        reference answer and that writes and DDL are refused.

    python provision.py agent
        Creates the demo agent through the public API (DA_API_BASE, DA_MASTER_KEY) for the
        owner DEMO_OWNER: no template, the sample database (host DEMO_DB_HOST), the business
        definitions as table descriptions, every table visible, and the suggested questions.
        The owner's model calls use the platform key. Finally the agent is flagged as the
        shared demo in the metadata database (DEMO_METADATA_DSN): there is deliberately no
        API for that, since a demo agent is shown to every signed-in user.

Environment values are libpq DSNs ("host=... port=... dbname=... user=... password=...").
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time

import psycopg2
import requests
from psycopg2 import sql

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE))
import build  # noqa: E402
import check_references  # noqa: E402

DB = "sample_ecommerce"
READER = "sample_ecommerce_reader"
CONFIG = json.loads((HERE / "agent.json").read_text(encoding="utf-8"))


def env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        sys.exit(f"{name} is not set")
    return value


def with_db(dsn: str, dbname: str, **override) -> str:
    """The same server as `dsn`, another database and optionally another user."""
    replaced = ("dbname",) + tuple(override)
    parts = [p for p in dsn.split() if p.split("=", 1)[0] not in replaced]
    return " ".join(parts + [f"dbname={dbname}"] + [f"{k}={v}" for k, v in override.items()])


def provision_database(replace: bool) -> None:
    admin, password = env("DEMO_ADMIN_DSN"), env("DEMO_READER_PASSWORD")
    conn = psycopg2.connect(admin)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB,))
        if cur.fetchone():
            if not replace:
                sys.exit(f"{DB} already exists; pass --replace to rebuild it")
            cur.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(DB)))
        cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DB)))
        cur.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(DB)))
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (READER,))
        verb = "ALTER" if cur.fetchone() else "CREATE"
        cur.execute(sql.SQL(
            verb + " ROLE {} LOGIN PASSWORD %s NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT "
            "NOREPLICATION CONNECTION LIMIT 20").format(sql.Identifier(READER)), (password,))
        for setting, value in (("default_transaction_read_only", "on"),
                               ("statement_timeout", "15s"),
                               ("idle_in_transaction_session_timeout", "60s")):
            cur.execute(sql.SQL("ALTER ROLE {} SET {} = {}").format(
                sql.Identifier(READER), sql.Identifier(setting), sql.Literal(value)))
        cur.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
            sql.Identifier(DB), sql.Identifier(READER)))
    conn.close()

    conn = psycopg2.connect(with_db(admin, DB))
    conn.autocommit = True  # the script carries its own BEGIN/COMMIT
    with conn.cursor() as cur:
        world = build.generate()
        cur.execute(build.to_sql(world))
        cur.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
        cur.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(READER)))
        cur.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA public TO {}").format(
            sql.Identifier(READER)))
    conn.close()
    print(f"loaded {DB}: {build.summary(world)}")

    reader = with_db(admin, DB, user=READER, password=password)
    if check_references.main(reader) != 0:
        sys.exit("reference answers do not match the loaded database")
    conn = psycopg2.connect(reader)
    conn.autocommit = True
    for statement in ("DELETE FROM orders", "UPDATE customers SET city = 'x'",
                      "CREATE TABLE scratch (id int)", "DROP TABLE returns"):
        try:
            with conn.cursor() as cur:
                cur.execute(statement)
            sys.exit(f"the reader role was able to run: {statement}")
        except psycopg2.Error as exc:
            print(f"refused as expected: {statement} -> {exc.pgcode} {exc.pgerror.splitlines()[0]}")
    conn.close()


class Api:
    def __init__(self):
        self.base = env("DA_API_BASE").rstrip("/")
        self.headers = {"X-API-Key": env("DA_MASTER_KEY"), "Content-Type": "application/json"}

    def __call__(self, method: str, path: str, body=None, ok=(200, 201, 202)):
        r = requests.request(method, self.base + path, headers=self.headers, json=body, timeout=300)
        try:
            data = r.json()
        except ValueError:
            data = r.text[:300]
        if r.status_code not in ok:
            sys.exit(f"{method} {path} -> {r.status_code}: {data}")
        return data


def tables(api: "Api", agent_id: str, db_id: str) -> dict:
    rows = api("GET", f"/agents/{agent_id}/databases/{db_id}/tables")["data"]
    return {r["table_name"]: r for r in rows}


def write_descriptions(api: "Api", agent_id: str, db_id: str) -> None:
    """Store the business definitions as the table descriptions, and prove they stuck.

    Adding a database starts a background job that writes generated descriptions for every
    table. Descriptions written while it runs are overwritten when it finishes (seen on
    2026-10-23: ours were replaced 14 s later). So wait until every table has a generated
    description, then write ours, then read them back.
    """
    deadline = time.time() + 300
    while time.time() < deadline:
        current = tables(api, agent_id, db_id)
        if set(CONFIG["tables"]) <= set(current) and all(
                (current[t].get("description") or "").strip() for t in CONFIG["tables"]):
            break
        time.sleep(5)
    else:
        sys.exit("generated table descriptions did not appear within 5 minutes")
    time.sleep(5)  # the job writes all tables in one transaction; leave it a moment to finish
    api("POST", f"/agents/{agent_id}/databases/{db_id}/tables", {"tables": [
        {"table_name": t, "description": d} for t, d in CONFIG["tables"].items()]})
    for table in CONFIG["tables"]:
        api("PATCH", f"/agents/{agent_id}/databases/{db_id}/tables/{table}/visibility",
            {"is_included": True})
    time.sleep(10)
    stored = tables(api, agent_id, db_id)
    wrong = [t for t, d in CONFIG["tables"].items()
             if stored[t].get("description") != d or stored[t].get("is_included") is not True]
    if wrong:
        sys.exit(f"descriptions or visibility did not persist for: {', '.join(wrong)}")
    print("business definitions stored and visible, read back:", ", ".join(CONFIG["tables"]))


def provision_agent() -> None:
    api, owner = Api(), env("DEMO_OWNER").lower()
    password, host = env("DEMO_READER_PASSWORD"), env("DEMO_DB_HOST")

    api("PATCH", f"/owners/{owner}/config", {
        "provider_key_source": "platform",
        # Visitors' demo questions are bounded by the demo allowance and monthly budget;
        # the owner's own cap would otherwise make every visitor share 20 a day.
        "platform_limits": {"max_queries_per_day": None}})
    print("owner config: platform key, no owner cap")

    agent = api("POST", "/agents", {"owner_id": owner, "agent_name": CONFIG["agent_name"],
                                    "greet_message": CONFIG["greet_message"], "template_id": None})
    agent_id = agent["agent_id"]
    print("agent", agent_id)

    spec = CONFIG["database"]
    added = api("POST", f"/agents/{agent_id}/databases", {
        "db_host": host, "db_port": int(os.environ.get("DEMO_DB_PORT", "5432")),
        "db_name": spec["db_name"], "db_user": spec["db_user"], "db_password": password,
        "db_engine": spec["db_engine"], "description": spec["description"]})
    db_id = added.get("db_id") or added.get("database", {}).get("db_id")
    print("database", db_id, added.get("status"))

    write_descriptions(api, agent_id, db_id)

    api("PATCH", f"/agents/{agent_id}/config/params", {
        "suggested_questions": CONFIG["suggested_questions"], "follow_up": True,
        "graph_output": True, "show_sql_query": True, "show_db_result": True})
    print("suggested questions:", len(CONFIG["suggested_questions"]))

    conn = psycopg2.connect(env("DEMO_METADATA_DSN"))
    with conn, conn.cursor() as cur:
        cur.execute("UPDATE chatbot_details SET is_demo = true WHERE agent_id = %s "
                    "AND lower(owner_id) = %s RETURNING agent_id", (agent_id, owner))
        assert cur.fetchone(), "agent not flagged"
    conn.close()
    print("flagged as the shared demo agent")
    # Column profiling runs in the background after the database is added.
    time.sleep(5)
    print(json.dumps({"agent_id": agent_id, "db_id": db_id}))


if __name__ == "__main__":
    step = sys.argv[1] if len(sys.argv) > 1 else ""
    if step == "database":
        provision_database(replace="--replace" in sys.argv)
    elif step == "agent":
        provision_agent()
    elif step == "descriptions":
        # Re-apply the definitions to an existing demo agent: DEMO_AGENT_ID, DEMO_DB_ID.
        write_descriptions(Api(), env("DEMO_AGENT_ID"), env("DEMO_DB_ID"))
    else:
        sys.exit("usage: provision.py database [--replace] | agent | descriptions")
