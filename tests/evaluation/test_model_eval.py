"""Offline checks of the model-evaluation grader, report and fixtures (no model, API or database)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))

from model_eval import grade, provision  # noqa: E402
from model_eval.run import load_dataset, report  # noqa: E402


def block(columns, rows):
    return {"columns": [{"name": c} for c in columns], "rows": [dict(zip(columns, r)) for r in rows]}


class ExactTableMatchTest(unittest.TestCase):
    expected = [["Lucas Thompson", "9953.07"], ["Diego Hill", "8596.40"]]

    def test_accepts_renamed_reordered_and_extra_columns(self):
        actual = block(["total", "customer_name", "orders"], [[9953.07, "lucas thompson", 3], [8596.4, "Diego Hill", 2]])
        self.assertTrue(grade.exact_table_match(self.expected, actual, ordered=True))

    def test_rejects_wrong_value_order_and_missing_rows(self):
        self.assertFalse(grade.exact_table_match(
            self.expected, block(["c", "t"], [["Lucas Thompson", 9953.17], ["Diego Hill", 8596.40]]), ordered=True))
        self.assertFalse(grade.exact_table_match(
            self.expected, block(["c", "t"], [["Diego Hill", 8596.40], ["Lucas Thompson", 9953.07]]), ordered=True))
        self.assertTrue(grade.exact_table_match(
            self.expected, block(["c", "t"], [["Diego Hill", 8596.40], ["Lucas Thompson", 9953.07]]), ordered=False))
        self.assertFalse(grade.exact_table_match(self.expected, block(["c", "t"], [["Lucas Thompson", 9953.07]]), ordered=True))
        self.assertFalse(grade.exact_table_match(self.expected, None, ordered=True))

    def test_rounding_tolerance_follows_reference_precision(self):
        self.assertTrue(grade.exact_table_match([["North", "66.7"]], block(["r", "p"], [["North", 66.6667]]), ordered=True))
        self.assertFalse(grade.exact_table_match([["North", "66.7"]], block(["r", "p"], [["North", 0.667]]), ordered=True))
        self.assertFalse(grade.exact_table_match([[3, 251]], block(["m", "n"], [[3, 252]]), ordered=True))


class SqlCheckTest(unittest.TestCase):
    def test_rejects_writes_and_multiple_statements_without_executing(self):
        never = lambda: (_ for _ in ()).throw(AssertionError("must not execute"))  # noqa: E731
        self.assertFalse(grade.sql_check("DELETE FROM orders", never)["read_only"])
        self.assertFalse(grade.sql_check("SELECT 1; SELECT 2", never)["parses"])
        self.assertFalse(grade.sql_check("", never)["present"])


class VerdictTest(unittest.TestCase):
    def test_correct_needs_matching_table_and_answer(self):
        verdict = {"table_verdict": "match", "answer_verdict": "correct"}
        self.assertTrue(grade.is_correct({"supported": True}, verdict))
        self.assertFalse(grade.is_correct({"supported": True}, dict(verdict, answer_verdict="partially_correct")))
        self.assertTrue(grade.is_correct({"supported": False}, {"table_verdict": "not_applicable", "answer_verdict": "correct"}))


class DatasetTest(unittest.TestCase):
    def test_every_case_resolves_to_ground_truth(self):
        spec, cases, digest = load_dataset()
        self.assertEqual(len({c["id"] for c in cases}), len(cases))
        self.assertEqual({c["fixture"] for c in cases}, {"ecommerce", "clinic"})
        for case in cases:
            if case.get("supported", True):
                self.assertTrue(case["expected"]["rows"], case["id"])
            else:
                self.assertIsNone(case["expected"])
        self.assertEqual(len(digest), 64)

    def test_clinic_references_rebuild_byte_for_byte(self):
        build = provision.load_module(REPO / "tests/evaluation/model_eval/fixtures/clinic/build.py", "clinic_build")
        world = build.generate()
        rebuilt = json.dumps({"seed": build.SEED, "row_counts": build.summary(world),
                              "answers": build.references(world)}, indent=2, default=str) + "\n"
        stored = (REPO / "tests/evaluation/model_eval/fixtures/clinic/reference_answers.json").read_text(encoding="utf-8")
        self.assertEqual(rebuilt, stored)

    def test_configs_name_only_available_models(self):
        for path in (HERE / "model_eval/configs").glob("*.json"):
            config = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(config["profile"], "futuresmart-recommended-v1", path.name)
            for binding in config.get("overrides", {}).values():
                self.assertIn(binding["model"], {"gpt-6.1-sol", "gpt-6-luna"}, path.name)


class ReportTest(unittest.TestCase):
    def test_report_compares_configs_and_lists_disagreements(self):
        def record(config, case, correct, latency, cost, exact, table):
            return {"config": config, "case_id": case, "fixture": "clinic", "http_status": 200, "correct": correct,
                    "sql_valid": True, "sql": {"present": True, "executes": True}, "server_latency_ms": latency,
                    "client_latency_ms": latency + 50, "estimated_cost_usd": cost, "cost_complete": True,
                    "exact_table_match": exact, "verdict": {"table_verdict": table, "answer_verdict": "correct",
                                                            "failure_kind": "none" if correct else "wrong_numbers",
                                                            "reason": "r"}}
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            rows = {"base": [record("base", "a", True, 10000, 0.02, True, "match"),
                             record("base", "b", True, 20000, 0.03, False, "match")],
                    "cheap": [record("cheap", "a", True, 4000, 0.002, True, "match"),
                              record("cheap", "b", False, 6000, 0.003, False, "mismatch")]}
            for config, records in rows.items():
                (out / f"results-{config}.jsonl").write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
            summary = report(out)
        self.assertEqual(summary["configs"]["base"]["overall"]["correct"], 2)
        self.assertEqual(summary["configs"]["cheap"]["overall"]["accuracy"], 0.5)
        self.assertEqual(summary["configs"]["cheap"]["overall"]["estimated_cost_usd_total"], 0.005)
        self.assertEqual(summary["cases"]["b"]["cheap"]["failure_kinds"], ["wrong_numbers"])
        self.assertEqual(len(summary["judge_exact_disagreements"]), 1)


if __name__ == "__main__":
    unittest.main()
