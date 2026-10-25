"""Load the evaluation databases and create one agent per database through the public API.

Databases: each fixture's builder generates the rows; they are loaded into a fresh database
with a SELECT-only reader role, and every reference answer is then checked twice — the
builder's plain-Python answer must equal the reference SQL run AS THE READER on the loaded
data. A disagreement stops the evaluation before any model is graded.

Agents: created exactly as the hosted Cedar Lane demo agent is (deploy/demo/ecommerce/
provision.py): no template, the business definitions written as table descriptions after
the background description job has finished, every table visible. Nothing here bypasses
the API the product uses.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import time
from decimal import Decimal
from pathlib import Path

import psycopg2
import requests
from psycopg2 import sql

REPO = Path(__file__).resolve().parents[3]


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses resolve their module while the class is built
    spec.loader.exec_module(module)
    return module


def normal(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, float):
        return str(round(value, 1))
    return value


def with_db(dsn: str, dbname: str, **override) -> str:
    replaced = ("dbname",) + tuple(override)
    parts = [p for p in dsn.split() if p.split("=", 1)[0] not in replaced]
    return " ".join(parts + [f"dbname={dbname}"] + [f"{k}={v}" for k, v in override.items()])


def load_database(admin_dsn: str, fixture: dict, reader_password: str) -> dict:
    """Create the fixture database from its builder; returns row counts. Replaces any copy."""
    build = load_module(REPO / fixture["builder"], f"build_{fixture['database']}")
    db, reader = fixture["database"], fixture["reader"]
    conn = psycopg2.connect(admin_dsn)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(db)))
        cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db)))
        cur.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(db)))
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (reader,))
        verb = "ALTER" if cur.fetchone() else "CREATE"
        cur.execute(sql.SQL(verb + " ROLE {} LOGIN PASSWORD %s NOSUPERUSER NOCREATEDB NOCREATEROLE")
                    .format(sql.Identifier(reader)), (reader_password,))
        cur.execute(sql.SQL("ALTER ROLE {} SET default_transaction_read_only = on").format(sql.Identifier(reader)))
        cur.execute(sql.SQL("ALTER ROLE {} SET statement_timeout = '30s'").format(sql.Identifier(reader)))
        cur.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(db), sql.Identifier(reader)))
    conn.close()
    conn = psycopg2.connect(with_db(admin_dsn, db))
    conn.autocommit = True
    world = build.generate()
    with conn.cursor() as cur:
        cur.execute(build.to_sql(world))
        cur.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
        cur.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(reader)))
        cur.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA public TO {}").format(sql.Identifier(reader)))
    conn.close()
    return build.summary(world)


def check_references(reader_dsn: str, fixture: dict) -> int:
    """Python-computed answers must equal the reference SQL on the loaded data."""
    answers = json.loads((REPO / fixture["references"]).read_text(encoding="utf-8"))["answers"]
    checked = 0
    with psycopg2.connect(reader_dsn) as conn, conn.cursor() as cur:
        for answer in answers:
            if not answer.get("reference_sql"):
                continue
            cur.execute(answer["reference_sql"])
            got = [[normal(v) for v in row] for row in cur.fetchall()]
            want = [[normal(v) for v in row] for row in answer["rows"]]
            if got != want:
                raise SystemExit(f"reference mismatch in {fixture['database']}: {answer['question']}")
            checked += 1
    return checked


class Api:
    def __init__(self, base: str, master_key: str):
        self.base = base.rstrip("/")
        self.headers = {"X-API-Key": master_key, "Content-Type": "application/json"}

    def __call__(self, method: str, path: str, body=None, ok=(200, 201, 202)):
        response = requests.request(method, self.base + path, headers=self.headers, json=body, timeout=300)
        if response.status_code not in ok:
            # Status and path only: application error bodies can echo connection details.
            raise SystemExit(f"{method} {path} -> HTTP {response.status_code}")
        return response.json()


def create_agent(api: Api, owner: str, fixture: dict, db_host: str, reader_password: str) -> dict:
    config = json.loads((REPO / fixture["agent"]).read_text(encoding="utf-8"))
    agent_id = api("POST", "/v1/agents", {"owner_id": owner, "agent_name": config["agent_name"],
                                          "template_id": None})["agent_id"]
    spec = config["database"]
    added = api("POST", f"/v1/agents/{agent_id}/databases", {
        "db_host": db_host, "db_port": 5432, "db_name": spec["db_name"], "db_user": spec["db_user"],
        "db_password": reader_password, "db_engine": spec["db_engine"], "description": spec["description"]})
    db_id = added.get("db_id") or added.get("database", {}).get("db_id")

    def tables():
        rows = api("GET", f"/v1/agents/{agent_id}/databases/{db_id}/tables")["data"]
        return {r["table_name"]: r for r in rows}

    # The setup job writes generated descriptions for every table and would overwrite ours
    # if we wrote first (DA-DESC-RACE-001); wait for it, then write the definitions.
    deadline = time.time() + 600
    while time.time() < deadline:
        current = tables()
        if set(config["tables"]) <= set(current) and all(
                (current[t].get("description") or "").strip() for t in config["tables"]):
            break
        time.sleep(5)
    else:
        raise SystemExit(f"generated descriptions did not appear for {spec['db_name']}")
    time.sleep(5)
    api("POST", f"/v1/agents/{agent_id}/databases/{db_id}/tables", {"tables": [
        {"table_name": t, "description": d} for t, d in config["tables"].items()]})
    for table in config["tables"]:
        api("PATCH", f"/v1/agents/{agent_id}/databases/{db_id}/tables/{table}/visibility", {"is_included": True})
    time.sleep(10)
    stored = tables()
    wrong = [t for t, d in config["tables"].items()
             if stored[t].get("description") != d or stored[t].get("is_included") is not True]
    if wrong:
        raise SystemExit(f"definitions did not persist for {spec['db_name']}: {', '.join(wrong)}")
    api("PATCH", f"/v1/agents/{agent_id}/config/params", {
        "follow_up": False, "graph_output": True, "show_sql_query": True, "show_db_result": True})
    return {"agent_id": agent_id, "db_id": db_id}


def agent_key(api: Api, owner: str, agent_id: str) -> str:
    """A fresh agent key for this run; held in memory only, never written to results."""
    return api("POST", f"/v1/agents/{agent_id}/api-keys", {"user_id": owner})["api_key"]
