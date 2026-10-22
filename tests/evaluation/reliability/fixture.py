"""Execute a frozen synthetic regression fixture, never a provider/product call."""
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from .oracle import Column, EvaluationFailure, compare_rows, compare_block, require, verify_support

FIXTURE = Path(__file__).parent / "fixtures" / "v1"
TABLES = ("customers", "orders", "items", "refunds")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def json_value(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def json_rows(rows):
    return [[json_value(v) for v in row] for row in rows]


def content_bytes(connection):
    data = {}
    for table in TABLES:
        with_cursor = connection.cursor()
        try:
            with_cursor.execute(f"SELECT * FROM {table} ORDER BY 1")
            data[table] = json_rows(with_cursor.fetchall())
        finally:
            with_cursor.close()
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode()


def verify_manifest(folder=FIXTURE):
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    actual_files = {p.relative_to(folder).as_posix() for p in folder.rglob("*")
                    if p.is_file() and p.name != "manifest.json"}
    require(actual_files == set(manifest["files"]), "Fixture manifest inventory differs")
    for name, expected in manifest["files"].items():
        require(digest((folder / name).read_bytes()) == expected, "Fixture bytes differ from versioned manifest")
    return manifest


def connect(backend):
    if backend == "sqlite":
        connection = sqlite3.connect(":memory:")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection
    require(backend == "postgres", "Unknown fixture engine")
    # Deliberately no DSN/app env-file/credential fallback or arbitrary host input.
    require(os.environ.get("EVAL_RELIABILITY_DISPOSABLE") == "1", "Explicit disposable PostgreSQL opt-in required")
    port_text = os.environ.get("EVAL_RELIABILITY_PORT", "")
    require(port_text.isascii() and port_text.isdecimal() and 1024 <= int(port_text) <= 65535,
            "Explicit unprivileged loopback test port required")
    import psycopg2
    connection = psycopg2.connect(
        host="127.0.0.1", port=int(port_text), dbname="eval_reliability",
        user="eval_fixture_admin", password="synthetic-ci-only", connect_timeout=3,
        options="-c statement_timeout=2000 -c lock_timeout=1000",
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute("CREATE SCHEMA eval_reliability_v1")
            cursor.execute("SET LOCAL search_path=eval_reliability_v1,pg_catalog")
    except Exception:
        connection.close()
        raise
    return connection


def initialize(connection, backend, folder=FIXTURE):
    for name in ("schema.sql", "data.sql"):
        sql = (folder / name).read_text(encoding="utf-8")
        if backend == "sqlite":
            connection.executescript(sql)
        else:
            with connection.cursor() as cursor:
                cursor.execute(sql)


def execute(connection, sql):
    cursor = connection.cursor()
    try:
        cursor.execute(sql)
        return [c[0] for c in cursor.description], cursor.fetchall()
    finally:
        cursor.close()


def block_for(names, rows):
    def kind(value):
        if value is None:
            return "null"
        if type(value) is bool:
            return "boolean"
        if type(value) is int:
            return "integer"
        if isinstance(value, (float, Decimal)):
            return "number"
        return "string"
    return {
        "columns": [{"name": n, "type": kind(next((r[i] for r in rows if r[i] is not None), None))}
                    for i, n in enumerate(names)],
        "rows": [dict(zip(names, [json_value(v) for v in row])) for row in rows],
        "row_count": len(rows), "truncated": False,
    }


def reference_sql(case, folder=FIXTURE):
    prefix = (folder / "qualified.sql").read_text(encoding="utf-8") if case.get("common") else ""
    return prefix + (folder / case["reference"]).read_text(encoding="utf-8")


def negative_sql(case, negative, folder=FIXTURE):
    if "sql" in negative:
        return negative["sql"]
    if "file" in negative:
        prefix = (folder / "qualified.sql").read_text(encoding="utf-8") if negative.get("common") else ""
        return prefix + (folder / negative["file"]).read_text(encoding="utf-8")
    sql = reference_sql(case, folder)
    key = "replace_once" if "replace_once" in negative else "replace_all"
    old, new = negative[key]
    require(sql.count(old) == 1 if key == "replace_once" else sql.count(old) >= 1,
            "Wrong SQL control no longer applies")
    return sql.replace(old, new, 1) if key == "replace_once" else sql.replace(old, new)


def run_fixture(backend, folder=FIXTURE):
    manifest = verify_manifest(folder)
    cases = json.loads((folder / "cases.json").read_text(encoding="utf-8"))["cases"]
    connection = connect(backend)
    report = {"fixture_version": "relational-v1", "engine": backend,
              "manifest_sha256": digest((folder / "manifest.json").read_bytes()),
              "provider_or_product_calls": 0, "cases": []}
    try:
        initialize(connection, backend, folder)
        initialized = content_bytes(connection)
        counts = {name: len(rows) for name, rows in json.loads(initialized).items()}
        require(len(counts) == manifest["tables"] and sum(counts.values()) == manifest["source_rows"],
                "Fixture table/row inventory differs")
        fingerprint = digest(initialized)
        require(fingerprint == manifest["content_sha256"], "Initialized fixture content differs")
        report["content_sha256"] = fingerprint
        report["source_table_rows"] = counts
        for case in cases:
            record = {"id": case["id"], "supported": case["supported"], "negative": []}
            report["cases"].append(record)
            if case["supported"]:
                columns = [Column(**c) for c in case["columns"]]
                sql = reference_sql(case, folder)
                names, rows = execute(connection, sql)
                compare_rows(names, rows, case["expected"], columns, ordered=case["ordered"])
                compare_block(block_for(names, rows), case["expected"], columns, ordered=case["ordered"])
                verify_support({"is_answered": True}, supported=True)
                record.update(reference_sql_sha256=digest(sql.encode()), columns=names,
                              actual=json_rows(rows), expected=case["expected"], positive="accepted")
            else:
                # A declared schema-support control, not a model's abstention decision.
                verify_support({"is_answered": False, "response": "Review ratings are unavailable in this schema.",
                                "debug_info": {"sql_query": "", "db_result": None}}, supported=False)
                record.update(positive="accepted_explicit_unavailable_validator_control", expected=None)
            for negative in case["negative"]:
                wrong_sql = negative_sql(case, negative, folder)
                names, rows = execute(connection, wrong_sql)  # Errors do NOT count as wrong-output rejection.
                outcome = {"id": negative["id"], "sql": wrong_sql,
                           "sql_sha256": digest(wrong_sql.encode()), "columns": names, "actual": json_rows(rows)}
                try:
                    if case["supported"]:
                        compare_rows(names, rows, case["expected"], columns, ordered=case["ordered"])
                        compare_block(block_for(names, rows), case["expected"], columns, ordered=case["ordered"])
                    else:
                        verify_support({"is_answered": True, "response": "Average rating is zero.",
                                        "debug_info": {"sql_query": wrong_sql, "db_result": block_for(names, rows)}},
                                       supported=False)
                except EvaluationFailure as error:
                    outcome.update(outcome="rejected", reason=str(error))
                else:
                    raise EvaluationFailure("Non-discriminating wrong-SQL control: " + negative["id"])
                record["negative"].append(outcome)
        require(digest(content_bytes(connection)) == fingerprint, "Evaluation changed fixture content")
        report["fixture_unchanged"] = True
        return report
    finally:
        try:
            connection.rollback()  # PostgreSQL schema/data are never committed.
            if backend == "postgres":
                names, rows = execute(connection, "SELECT to_regnamespace('eval_reliability_v1') IS NULL AS schema_removed")
                require(rows == [(True,)], "Disposable schema rollback not verified")
                connection.rollback()
                report["cleanup"] = "schema_rollback_verified"
            else:
                report["cleanup"] = "in_memory_connection_closed"
        finally:
            connection.close()
