"""Real HTTP + model + read-only fixture check. Never prints credentials/bodies."""
from contextlib import closing
import sys
from pathlib import Path

backend = Path(__file__).resolve().parents[2] / "backend"
if backend.is_dir():
    sys.path.insert(0, str(backend))
import os
from decimal import Decimal

from reliability.oracle import Column, EvaluationFailure, require, compare_rows, compare_block, verify_support, verify_sales_narrative


def fixture_connection():
    import psycopg2
    return psycopg2.connect(
        host=os.getenv("SAMPLE_HOST", "sample-db"), port=int(os.getenv("SAMPLE_PORT", "5432")),
        dbname="sample_sales", user="sample_reader", password="local-reader-only",
    )


def verify_fixture():
    import psycopg2
    with fixture_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT region, SUM(amount) FROM public.orders GROUP BY region ORDER BY region")
            require(cursor.fetchall() == [("North", Decimal("250.00")), ("South", Decimal("200.00"))],
                    "Installation fixture differs from known reference")
    # Prove table ACLs deny writes even if the role overrides its read-only default.
    for statement in ("UPDATE public.orders SET amount=0", "DROP TABLE public.orders", "CREATE TABLE public.forbidden(id int)", "CREATE TEMP TABLE forbidden(id int)"):
        connection = fixture_connection()
        try:
            connection.set_session(readonly=False)
            with connection.cursor() as cursor:
                try:
                    cursor.execute(statement)
                except psycopg2.errors.InsufficientPrivilege:
                    pass
                else:
                    raise AssertionError("Fixture reader unexpectedly permitted a write")
        finally:
            connection.rollback()
            connection.close()
    print("PASS fixture known answer and read-only grants (four denied writes)")


def request(client, method, path, **kwargs):
    response = client.request(method, path, **kwargs)
    if response.is_error:
        raise RuntimeError(f"HTTP {response.status_code} at {method} {path}")
    return response.json()


def verify_answer(result, connection_factory=None):
    import sqlglot
    from sqlglot import exp

    verify_support(result, supported=True)
    debug = result.get("debug_info")
    require(isinstance(debug, dict), "API omitted debug metadata")
    sql = debug.get("sql_query", "")
    require(isinstance(sql, str) and bool(sql.strip()), "API omitted SQL")
    try:
        statements = sqlglot.parse(sql, read="postgres")
    except sqlglot.errors.ParseError as error:
        raise EvaluationFailure("SQL did not parse") from error
    require(len(statements) == 1 and isinstance(statements[0], (exp.Select, exp.Union)), "Expected a SELECT")
    require(not any(statements[0].find_all(exp.Insert, exp.Update, exp.Delete, exp.Create, exp.Drop)), "Expected read-only SQL")
    with (connection_factory or fixture_connection)() as connection:
        with closing(connection.cursor()) as cursor:
            cursor.execute(sql)
            rows = cursor.fetchall()
            names = [column[0] for column in cursor.description]
    expected = [("North", Decimal("250.00")), ("South", Decimal("200.00"))]
    columns = [Column("region", "text"), Column("total_amount", "decimal", unit="USD", scale=2)]
    # The existing question explicitly requests region/total_amount ordered by region.
    compare_rows(names, rows, expected, columns, ordered=True)
    block = result["debug_info"].get("db_result")
    compare_block(block, expected, columns, ordered=True)
    verify_sales_narrative(result.get("response", ""), expected)


def main():
    import httpx
    from runtime_config import load_environment
    load_environment()
    verify_fixture()
    if "--fixture-only" in sys.argv[1:]:
        return
    base = os.getenv("SMOKE_API_URL", "http://api:8000/nl2sql/api")
    if not base.startswith(("http://api:", "http://127.0.0.1:", "http://localhost:")):
        raise RuntimeError("Smoke API must be the local disposable stack")
    with httpx.Client(base_url=base + "/", timeout=180, headers={"X-API-Key": os.environ["FASTAPI_SECRET_KEY"]}) as client:
        request(client, "GET", "health")
        schema = request(client, "GET", "openapi.json")
        assert "/v1/agents" in schema["paths"]
        print("PASS health and OpenAPI (not model proof)")
        owner = "fixture@example.test"
        agent = request(client, "POST", "v1/agents", json={
            "owner_id": owner, "agent_name": "Synthetic first-run smoke", "template_id": None,
            "temperature": 0,
            "show_sql_query": True, "show_db_result": True,
        })["agent_id"]
        prefix = f"v1/agents/{agent}"
        database = request(client, "POST", prefix + "/databases", json={
            "db_host": os.getenv("SAMPLE_HOST", "sample-db"), "db_port": int(os.getenv("SAMPLE_PORT", "5432")),
            "db_name": "sample_sales", "db_user": "sample_reader", "db_password": "local-reader-only",
            "db_engine": "postgresql", "description": "Synthetic orders by region. amount is revenue in USD.",
        })["db_id"]
        request(client, "POST", prefix + f"/databases/{database}/tables", json={"tables": [
            {"table_name": "orders", "description": "Synthetic orders: order_id, region, amount (USD revenue)."}
        ]})
        key = request(client, "POST", prefix + "/api-keys", json={"user_id": owner})["api_key"]
        print("PASS master-key agent/database/table setup and agent-key issuance")
        result = request(client, "POST", prefix + "/chat?stream=false", headers={"X-API-Key": key}, json={
            "query": "What is the total amount for each region in orders? Return region and total_amount, ordered by region. State both region totals in the answer.",
            "debug_info": True, "chart_output": False, "follow_up": False,
        })
        verify_answer(result)
        print("PASS real model + PostgreSQL journey: North=250.00, South=200.00; chart not requested")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Existing application errors can include credentials; only display safe failure class.
        print(f"FAIL first-run smoke ({type(error).__name__}); inspect local redacted application diagnostics")
        raise SystemExit(1) from None
