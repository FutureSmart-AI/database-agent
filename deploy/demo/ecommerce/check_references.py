"""Check the reference answers against SQL run on a loaded Cedar Lane sample database.

reference_answers.json is computed in Python from the generated rows (build.py). Each
answer's `reference_sql` is run here on PostgreSQL and its rows must equal the Python
answer exactly, so every reference answer is confirmed by two independent computations.

    python check_references.py "host=... port=5432 dbname=sample_ecommerce user=... password=..."

Exits non-zero on any mismatch. Prints rows, never the connection string.
"""
import json
import pathlib
import sys
from decimal import Decimal

import psycopg2


def normal(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, float):
        return str(round(value, 1))
    return value


def main(dsn: str) -> int:
    answers = json.loads((pathlib.Path(__file__).with_name("reference_answers.json"))
                         .read_text(encoding="utf-8"))["answers"]
    failures = 0
    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        for answer in answers:
            if not answer["reference_sql"]:
                print(f"SKIP  {answer['question']} (same rows as an earlier question)")
                continue
            cur.execute(answer["reference_sql"])
            got = [[normal(v) for v in row] for row in cur.fetchall()]
            want = [[normal(v) for v in row] for row in answer["rows"]]
            ok = got == want
            failures += not ok
            print(f"{'OK  ' if ok else 'FAIL'}  {answer['question']}")
            if not ok:
                print(f"      sql:    {got}\n      python: {want}")
    print(f"{len(answers)} answers, {failures} mismatched")
    return 1 if failures else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: check_references.py DSN")
    sys.exit(main(sys.argv[1]))
