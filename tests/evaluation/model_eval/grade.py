"""Grade one API answer against ground truth.

Three independent checks per answer:

* ``sql_check`` — mechanical: the returned SQL parses as one read-only SELECT and runs on
  the evaluation database as the read-only role.
* ``exact_table_match`` — mechanical: the returned rows contain the expected rows, column
  by column, with numbers equal up to the precision the reference states. It cannot
  recognise an equivalent representation (month 3 vs '2025-03-01', a ratio vs a percent),
  so it is recorded as evidence, never as the verdict.
* ``judge`` — the verdict: an LLM given the question, the business definition, the
  ground-truth rows, the returned rows, the SQL and the prose answer, returning structured
  output (verdicts, failure kind, reason, confidence). Disagreements with the exact check
  are listed in the report for review.

Accuracy here is measured against ground truth; nothing is a self-reported confidence.
"""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

JUDGE_MODEL = "gpt-6.1-sol"
JUDGE_EFFORT = "medium"
JUDGE_ROWS = 60


# ── SQL validity ────────────────────────────────────────────────────────────

def sql_check(sql_text: Optional[str], connection_factory) -> dict:
    import sqlglot
    from sqlglot import exp

    if not sql_text or not sql_text.strip():
        return {"present": False, "parses": False, "read_only": False, "executes": False}
    out = {"present": True, "parses": False, "read_only": False, "executes": False}
    try:
        statements = [s for s in sqlglot.parse(sql_text, read="postgres") if s is not None]
    except sqlglot.errors.ParseError:
        return out
    out["parses"] = len(statements) == 1
    if not out["parses"]:
        return out
    tree = statements[0]
    out["read_only"] = isinstance(tree, (exp.Select, exp.Union, exp.With, exp.Subquery)) and not any(
        tree.find_all(exp.Insert, exp.Update, exp.Delete, exp.Create, exp.Drop, exp.Alter))
    if not out["read_only"]:
        return out
    try:
        with connection_factory() as conn, conn.cursor() as cur:
            cur.execute(sql_text)
            out["rows"] = len(cur.fetchall())
            out["executes"] = True
            conn.rollback()
    except Exception as error:  # the error class only: messages can quote data
        out["error"] = type(error).__name__
    return out


# ── Mechanical table comparison ─────────────────────────────────────────────

def _number(value) -> Optional[Decimal]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return Decimal(str(value).replace(",", "").replace("$", "").strip())
    except (InvalidOperation, ValueError):
        return None


def _same(expected, actual) -> bool:
    e, a = _number(expected), _number(actual)
    if e is not None and a is not None:
        places = max(-e.as_tuple().exponent, 0) if isinstance(expected, str) else 0
        tolerance = Decimal(1).scaleb(-places) / 2 if places else Decimal("0.5")
        if isinstance(expected, int):
            tolerance = Decimal(0)
        return abs(e - a) <= tolerance + Decimal("1e-9")
    return str(expected).strip().casefold() == str(actual).strip().casefold()


def exact_table_match(expected_rows: list, actual_block: Optional[dict], ordered: bool) -> bool:
    """Every expected column is found among the returned columns, row for row."""
    if not actual_block or not actual_block.get("rows"):
        return False
    names = [c["name"] for c in actual_block.get("columns") or []] or list(actual_block["rows"][0])
    actual = [[row.get(n) for n in names] for row in actual_block["rows"]]
    if len(actual) != len(expected_rows) or not expected_rows:
        return False
    width = len(expected_rows[0])

    def rows_match(mapping) -> bool:
        projected = [[row[i] for i in mapping] for row in actual]
        if ordered:
            return all(all(_same(e, a) for e, a in zip(er, ar)) for er, ar in zip(expected_rows, projected))
        remaining = list(projected)
        for er in expected_rows:
            hit = next((ar for ar in remaining if all(_same(e, a) for e, a in zip(er, ar))), None)
            if hit is None:
                return False
            remaining.remove(hit)
        return True

    def search(prefix):
        if len(prefix) == width:
            return rows_match(prefix)
        return any(search(prefix + [i]) for i in range(len(names)) if i not in prefix)

    return search([])


# ── LLM judge ───────────────────────────────────────────────────────────────

class Verdict(BaseModel):
    table_verdict: Literal["match", "mismatch", "no_table", "not_applicable"] = Field(
        description="Do the returned rows contain the facts the question asks for, equal to the ground truth? "
                    "not_applicable only for an unanswerable question.")
    answer_verdict: Literal["correct", "partially_correct", "incorrect"] = Field(
        description="Is the prose answer correct against the ground truth (or, for an unanswerable "
                    "question, does it decline without inventing values)?")
    failure_kind: Literal["none", "wrong_numbers", "wrong_entities", "missing_or_extra_rows",
                          "wrong_business_definition", "wrong_scale_or_unit", "refused_answerable",
                          "answered_unanswerable", "invented_values", "chart_missing", "other"]
    reason: str = Field(description="One or two sentences naming the concrete discrepancy, or why it is correct.")
    confidence: Literal["high", "medium", "low"]


JUDGE_INSTRUCTIONS = """You grade answers from a natural-language-to-SQL agent against ground truth.
Ground truth was computed independently and is correct. Judge only facts, not style.
- Representation differences are fine: column names, column order, month 3 vs 'March' vs '2025-03-01',
  extra helper columns, rounding that agrees at the precision of the ground truth, money with or
  without a currency symbol, and a fraction column (0.102) for a percentage (10.2) when the answer
  states the percentage correctly.
- Different facts are not fine: other numbers, other or missing entities, a fraction presented as the
  percentage (0.102%), rows from a different business definition, or a truncated list when the
  question asked for all groups.
- When the question asks for "the highest" or "the top", the ranking must agree with the ground truth;
  returning all groups in the right order is fine.
- If a chart was requested, a missing chart makes the answer partially_correct with failure_kind chart_missing.
- For an unanswerable question, correct means the answer says the data cannot answer it and gives
  no invented value; a SQL query over unrelated columns presented as the answer is incorrect."""


def judge(client, case: dict, expected: Optional[dict], response: dict) -> dict:
    debug = response.get("debug_info") or {}
    block = debug.get("db_result") or {}
    payload = {
        "question": case["question"],
        "answerable": case.get("supported", True),
        "business_definition": case.get("definition"),
        "ground_truth": None if expected is None else {
            "columns": expected["columns"], "rows": expected["rows"], "ordered": case.get("ordered", False)},
        "chart_requested": bool(case.get("chart")),
        "chart_returned": bool((response.get("chart_output") or {}).get("chart_data")),
        "agent_sql": debug.get("sql_query"),
        "agent_rows": {"columns": [c.get("name") for c in block.get("columns") or []],
                       "rows": (block.get("rows") or [])[:JUDGE_ROWS],
                       "row_count": block.get("row_count")},
        "agent_answer": response.get("response"),
    }
    result = client.responses.parse(
        model=JUDGE_MODEL, reasoning={"effort": JUDGE_EFFORT}, store=False,
        instructions=JUDGE_INSTRUCTIONS,
        input=json.dumps(payload, default=str), text_format=Verdict)
    verdict = result.output_parsed.model_dump()
    usage = getattr(result, "usage", None)
    verdict["judge_model"] = JUDGE_MODEL
    verdict["judge_tokens"] = {"input": getattr(usage, "input_tokens", None),
                               "output": getattr(usage, "output_tokens", None)}
    return verdict


def is_correct(case: dict, verdict: dict) -> bool:
    if not case.get("supported", True):
        return verdict["answer_verdict"] == "correct"
    return verdict["table_verdict"] == "match" and verdict["answer_verdict"] == "correct"
