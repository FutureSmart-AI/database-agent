"""Discriminating provider-free oracle and real SQLite SQL regressions."""
import copy
from decimal import Decimal
import importlib.util
from pathlib import Path
import sqlite3
import shutil
import tempfile
import unittest
from unittest.mock import patch

from reliability.fixture import run_fixture, block_for, verify_manifest, FIXTURE
from reliability.oracle import (
    Column, EvaluationFailure, UnsupportedAnswerFormat, canonical,
    compare_rows, compare_block, verify_support, verify_sales_narrative,
)

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
SALES = [Column("region", "text"), Column("total_amount", "decimal", unit="USD", scale=2)]
EXPECTED = [["North", "250.00"], ["South", "200.00"]]


def sales_block():
    return block_for([c.name for c in SALES], [("North", Decimal("250.00")), ("South", Decimal("200.00"))])


class TypedResultTests(unittest.TestCase):
    def test_complete_associated_values_and_named_column_reordering(self):
        block = sales_block()
        compare_block(block, EXPECTED, SALES, ordered=True)
        block["columns"].reverse()
        compare_block(block, EXPECTED, SALES, ordered=True)
        compare_rows(["total_amount", "region"], [[250, "North"], [200, "South"]],
                     EXPECTED, SALES, ordered=True)

    def test_wrong_complete_wire_results_are_rejected(self):
        def swapped(b):
            b["rows"][0]["total_amount"], b["rows"][1]["total_amount"] = 200, 250

        def tenfold(b):
            for row in b["rows"]:
                row["total_amount"] = str(Decimal(row["total_amount"]) * 10)

        def removed(b):
            b["rows"].pop()
            b["row_count"] = 1

        def extra(b):
            b["rows"].append({"region": "East", "total_amount": 0})
            b["row_count"] = 3

        def duplicate(b):
            b["rows"][1] = copy.deepcopy(b["rows"][0])

        mutations = {
            "swapped": swapped, "tenfold": tenfold, "missing": removed, "extra": extra,
            "duplicate_replacing_an_entity": duplicate,
            "wrong_order": lambda b: b["rows"].reverse(),
            "truncated": lambda b: b.update(truncated=True),
            "missing_truncation_flag": lambda b: b.pop("truncated"),
            "false_row_count": lambda b: b.update(row_count=200),
            "unnamed_wire_rows": lambda b: b.update(rows=[["North", 250], ["South", 200]]),
            "boolean_row_count": lambda b: b.update(row_count=True),
            "wrong_unit": lambda b: b["columns"][1].update(unit="EUR"),
            "wrong_metadata_type": lambda b: b["columns"][1].update(type="string"),
            "duplicate_columns": lambda b: b["columns"].append(copy.deepcopy(b["columns"][0])),
            "missing_field": lambda b: b["rows"][0].pop("total_amount"),
            "extra_field": lambda b: b["rows"][0].update(unexpected=250),
            "boolean_as_money": lambda b: b["rows"][0].update(total_amount=True),
            "null_as_money": lambda b: b["rows"][0].update(total_amount=None),
            "nonintegral_scale": lambda b: b["rows"][0].update(total_amount="250.001"),
            "nan": lambda b: b["rows"][0].update(total_amount=float("nan")),
            "infinity": lambda b: b["rows"][0].update(total_amount="Infinity"),
        }
        for name, change in mutations.items():
            with self.subTest(name=name):
                block = sales_block()
                change(block)
                with self.assertRaises(EvaluationFailure):
                    compare_block(block, EXPECTED, SALES, ordered=True)

    def test_order_policy_is_explicit_and_multiset_keeps_duplicate_multiplicity(self):
        cols = [Column("value", "integer")]
        compare_rows(["value"], [[2], [1], [1]], [[1], [2], [1]], cols, ordered=False)
        for rows in ([[2], [2], [1]], [[1], [2]], [[1], [1], [2], [2]]):
            with self.subTest(rows=rows), self.assertRaises(EvaluationFailure):
                compare_rows(["value"], rows, [[1], [1], [2]], cols, ordered=False)

    def test_numeric_null_boolean_rounding_and_tolerance_contracts(self):
        self.assertEqual(canonical("1.00", Column("n", "integer")), Decimal(1))
        for bad in (True, False, "1.1", float("inf"), "NaN", Decimal("NaN"), "250 USD"):
            with self.subTest(bad=str(bad)), self.assertRaises(EvaluationFailure):
                canonical(bad, Column("n", "integer"))
        self.assertIsNone(canonical(None, Column("n", "decimal", nullable=True)))
        for bad in (0, 1, "true", "false", "0"):
            with self.subTest(bad=bad), self.assertRaises(EvaluationFailure):
                canonical(bad, Column("flag", "boolean"))
        self.assertIs(canonical(True, Column("flag", "boolean")), True)
        self.assertEqual(canonical("1.235", Column("n", "decimal", scale=2, rounding="half_even")), Decimal("1.24"))
        self.assertEqual(canonical("1.245", Column("n", "decimal", scale=2, rounding="half_even")), Decimal("1.24"))
        with self.assertRaises(EvaluationFailure):
            canonical("1.235", Column("n", "decimal", scale=2))
        cols = [Column("n", "decimal", absolute_tolerance=Decimal("0.05"))]
        # A greedy matcher fails this correct multiset; one-to-one matching must reassign.
        compare_rows(["n"], [["0.05"], [0]], [[0], ["0.1"]], cols, ordered=False)
        with self.assertRaises(EvaluationFailure):
            compare_rows(["n"], [[0], [0]], [[0], ["0.1"]], cols, ordered=False)
        with self.assertRaises(EvaluationFailure):
            compare_rows(["n"], [["0.151"]], [["0.1"]], cols, ordered=True)
        with self.assertRaises(EvaluationFailure):
            compare_rows(["n"], [["0.01"]], [[0]], [Column("n", "decimal")], ordered=True)

    def test_null_is_not_zero_and_declared_boolean_is_not_integer(self):
        cols = [Column("n", "decimal", nullable=True), Column("flag", "boolean")]
        compare_rows(["n", "flag"], [[None, False]], [[None, False]], cols, ordered=True)
        for wrong in ([[0, False]], [[None, 0]]):
            with self.assertRaises(EvaluationFailure):
                compare_rows(["n", "flag"], wrong, [[None, False]], cols, ordered=True)


class AnswerAndSupportTests(unittest.TestCase):
    def test_known_sales_narrative_formats(self):
        for text in ("North: USD 250.00; South: USD 200.00.",
                     "Here are the totals by region: North is $250.00 and South is $200.00.",
                     "| Region | Total amount (USD) |\n|---|---|\n| **North** |250|\n| South |200|"):
            with self.subTest(text=text):
                verify_sales_narrative(text, EXPECTED)

    def test_swapped_tenfold_conflicting_units_repeated_and_unassociated_claims(self):
        for text in ("North: 200; South: 250", "North: 2500; South: 2000",
                     "North: 250 cents; South: 200 cents", "North: EUR250; South: EUR200",
                     "North: 250%; South: 200%", "North:250; North:200; South:200",
                     "South:200. North:250. Combined450.", "250 is the North value; South:200",
                     "These are false claims: North:250; South:200", "North is not250; South200"):
            with self.subTest(text=text), self.assertRaises(EvaluationFailure):
                verify_sales_narrative(text, EXPECTED)

    def test_currency_preamble_and_ambiguous_negative_formats_do_not_lose_units_or_sign(self):
        for text in ("₹ North:250; South:200", "₽ North:250; South:200",
                     "₩ North:250; South:200", "North: -$250; South:$200",
                     "North: ($250); South:$200", "North: $-250; South:$200",
                     "North: (USD250); South: (USD200)",
                     "North:250-; South:200", "-$ North:250; South:200"):
            with self.subTest(text=text), self.assertRaises(EvaluationFailure):
                verify_sales_narrative(text, EXPECTED)

    def test_unrecognized_correct_prose_is_manual_review_not_model_factual_error(self):
        with self.assertRaises(UnsupportedAnswerFormat):
            verify_sales_narrative("North earned250, with South earning200", EXPECTED)

    def test_unsupported_is_distinct_from_supported_zero(self):
        unavailable = {"is_answered": False, "response": "Review ratings are unavailable.", "debug_info": None}
        verify_support(unavailable, supported=False)
        verify_support({"is_answered": True}, supported=True)
        for result in ({"is_answered": True, "response": "0"},
                       {"is_answered": None, "response": "Unavailable"},
                       {"is_answered": False, "response": "Unavailable, count0"},
                       {"is_answered": False, "response": "Unavailable", "debug_info": {"sql_query": "SELECT 0"}},
                       {"is_answered": False, "response": "Unavailable", "debug_info": {"db_result": sales_block()}}):
            with self.subTest(result=result), self.assertRaises(EvaluationFailure):
                verify_support(result, supported=False)
        with self.assertRaises(EvaluationFailure):
            verify_support(unavailable, supported=True)

    def test_unavailable_prose_rejects_contradictions_and_extra_spelled_out_claims(self):
        for answer in ("Ratings are unavailable.", "Review ratings are unavailable in this schema.",
                       "Review ratings are not available in this schema."):
            verify_support({"is_answered": False, "response": answer, "debug_info": None}, supported=False)
        for answer in ("Ratings are not unavailable.", "Ratings are available, not unavailable.",
                       "Ratings are unavailable. Average rating is five.",
                       "Ratings are unavailable, average rating is zero.",
                       "Average rating is five so ratings are unavailable."):
            # Same false flag/no debug/no Arabic digits: the prose contract itself
            # must reject, not only the support flag or a digit-presence shortcut.
            with self.subTest(answer=answer), self.assertRaises(UnsupportedAnswerFormat):
                verify_support({"is_answered": False, "response": answer, "debug_info": None}, supported=False)


class RealSQLTests(unittest.TestCase):
    def test_versioned_fixture_rejects_silent_golden_or_data_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "v1"
            shutil.copytree(FIXTURE, folder)
            verify_manifest(folder)
            cases = folder / "cases.json"
            cases.write_bytes(cases.read_bytes() + b"\n")
            with self.assertRaises(EvaluationFailure):
                verify_manifest(folder)

    def test_relational_references_and_discriminating_wrong_sql_on_real_sqlite(self):
        with patch("socket.socket", side_effect=AssertionError("No network allowed")):
            result = run_fixture("sqlite")
        self.assertEqual(len(result["cases"]), 9)
        self.assertTrue(result["fixture_unchanged"])
        self.assertEqual(len(next(x for x in result["cases"] if x["id"] == "complete_pairs")["actual"]), 55)
        self.assertTrue(all(n["outcome"] == "rejected" for c in result["cases"] for n in c["negative"]))

    def test_actual_smoke_function_replays_actual_demo_sql_then_rejects_wrong_wire_or_prose(self):
        spec = importlib.util.spec_from_file_location("smoke_under_test", HERE / "run.py")
        smoke = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(smoke)
        connection = sqlite3.connect(":memory:")
        connection.execute("ATTACH DATABASE ':memory:' AS public")
        original_demo = (ROOT / "deploy/sample.sql").read_text(encoding="utf-8")
        # Exact CREATE/INSERT bytes from the untouched demo, excluding PG ACL syntax.
        connection.executescript(original_demo[original_demo.index("CREATE TABLE"):original_demo.index("CREATE ROLE")])
        good = {"is_answered": True, "response": "North: USD250; South: USD200.",
                "debug_info": {"sql_query": "SELECT region, SUM(amount) AS total_amount FROM public.orders GROUP BY region ORDER BY region",
                               "db_result": sales_block()}}
        try:
            with patch("socket.socket", side_effect=AssertionError("No network allowed")):
                smoke.verify_answer(good, connection_factory=lambda: connection)
                for mode in ("swapped_both", "tenfold_both", "wrong_prose_only", "wrong_sql_order", "wrong_actual_sql"):
                    bad = copy.deepcopy(good)
                    if mode in ("swapped_both", "wrong_prose_only"):
                        bad["response"] = "North:200; South:250"
                    if mode == "swapped_both":
                        bad["debug_info"]["db_result"]["rows"] = [{"region": "North", "total_amount": 200}, {"region": "South", "total_amount": 250}]
                    if mode == "tenfold_both":
                        bad["response"] = "North:2500; South:2000"
                        bad["debug_info"]["db_result"]["rows"] = [{"region": "North", "total_amount": 2500}, {"region": "South", "total_amount": 2000}]
                    if mode == "wrong_sql_order":
                        bad["debug_info"]["sql_query"] += " DESC"
                    if mode == "wrong_actual_sql":
                        bad["debug_info"]["sql_query"] = bad["debug_info"]["sql_query"].replace("SUM(amount)", "SUM(amount)*10")
                    with self.subTest(mode=mode), self.assertRaises(EvaluationFailure):
                        smoke.verify_answer(bad, connection_factory=lambda: connection)
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
