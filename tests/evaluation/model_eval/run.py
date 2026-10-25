"""Database Agent model evaluation: ask the real API, grade against ground truth, compare configs.

    prepare                     load both evaluation databases, check references, create agents
    ask --config NAME           ask every case through the chat API with the running model config
    report                      compare every config in the results directory

The API must already be running with the model configuration under test
(MODEL_CONFIG_PATH -> configs/NAME.json); `ask` refuses to grade answers whose recorded
models differ from that configuration. Runs inside the Compose network (see README.md).
Secrets come from the environment and are never printed or written to results.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import subprocess
import sys
import time
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE.parent))
for candidate in (REPO / "backend", Path("/app")):
    if (candidate / "agent").is_dir():
        sys.path.insert(0, str(candidate))

from model_eval import grade, provision  # noqa: E402

API = os.getenv("MODEL_EVAL_API", "http://api:8000/nl2sql/api")
DB_HOST = os.getenv("MODEL_EVAL_DB_HOST", "eval-db")
ADMIN_DSN = f"host={DB_HOST} port=5432 dbname=postgres user=eval_admin password=synthetic-eval-only"
READER_PASSWORD = "synthetic-eval-reader"  # synthetic, disposable, loopback/Compose-network only
OWNER = "model-eval@example.test"
SERVER_PROJECT = "database-agent-model-eval-server"


def sha256(paths) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.relative_to(REPO).as_posix().encode())
        digest.update((REPO / path).read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()


def load_dataset() -> tuple[dict, list, str]:
    spec = json.loads((HERE / "dataset.json").read_text(encoding="utf-8"))
    files = [HERE / "dataset.json"]
    references = {}
    for name, fixture in spec["fixtures"].items():
        for key in ("builder", "agent", "references"):
            files.append(REPO / fixture[key])
        answers = json.loads((REPO / fixture["references"]).read_text(encoding="utf-8"))["answers"]
        references[name] = {a.get("id") or a["question"]: a for a in answers}
    cases = []
    for case in spec["cases"]:
        case = dict(case)
        if case.get("supported", True):
            reference = references[case["fixture"]][case["reference"]]
            case.setdefault("question", reference["question"])
            case.setdefault("definition", reference.get("definition"))
            case.setdefault("ordered", reference.get("ordered", False))
            case["expected"] = {"columns": reference["columns"], "rows": reference["rows"]}
        else:
            case["expected"] = None
        cases.append(case)
    return spec, cases, sha256(files)


def master_key() -> str:
    from runtime_config import load_environment
    load_environment()
    return os.environ["FASTAPI_SECRET_KEY"]


def git_sha() -> str:
    sha = os.getenv("GITHUB_SHA")
    if sha:
        return sha
    try:
        return subprocess.check_output(["git", "-C", str(REPO), "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


# ── prepare ─────────────────────────────────────────────────────────────────

def prepare(out: Path) -> None:
    spec, cases, digest = load_dataset()
    api = provision.Api(API, master_key())
    api("PATCH", f"/v1/owners/{OWNER}/config", {"provider_key_source": "platform",
                                                "platform_limits": {"max_queries_per_day": None}})
    state = {"dataset_sha256": digest, "agents": {}}
    for name, fixture in spec["fixtures"].items():
        counts = provision.load_database(ADMIN_DSN, fixture, READER_PASSWORD)
        reader = provision.with_db(ADMIN_DSN, fixture["database"], user=fixture["reader"], password=READER_PASSWORD)
        checked = provision.check_references(reader, fixture)
        print(f"PASS {name}: loaded {counts}; {checked} reference answers equal their SQL on the loaded data")
        state["agents"][name] = provision.create_agent(api, OWNER, fixture, DB_HOST, READER_PASSWORD)
        print(f"PASS {name}: agent created through the API with business definitions as table descriptions")
    out.mkdir(parents=True, exist_ok=True)
    (out / "state.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


# ── ask ─────────────────────────────────────────────────────────────────────

def expected_models(config_path: Path) -> dict:
    from agent.utils.model_profiles import load_profile
    profile = load_profile(config_path)
    used = {b["model"] for group, ops in profile.items() if isinstance(ops, dict)
            for b in ops.values() if isinstance(b, dict) and "model" in b}
    return {"any": used, "sql_gen": profile["sql_agent"]["sql_generation"]["model"],
            "final_answer": profile["sql_agent"]["rephrase_answer"]["model"]}


def config_matches(usage: dict, models: dict) -> bool:
    nodes = {n["node"]: n["model"] for n in usage.get("nodes", []) if n.get("model")}
    if not nodes or not set(nodes.values()) <= models["any"]:
        return False
    return all(nodes.get(node, models[node]) == models[node] for node in ("sql_gen", "final_answer"))


def ask(out: Path, config: str, repeats: int, upload: bool) -> None:
    import httpx
    import psycopg2
    from openai import OpenAI

    spec, cases, digest = load_dataset()
    state = json.loads((out / "state.json").read_text(encoding="utf-8"))
    if state["dataset_sha256"] != digest:
        raise SystemExit("dataset changed since prepare; run prepare again")
    config_path = HERE / "configs" / f"{config}.json"
    models = expected_models(config_path)
    config_sha = sha256([config_path])
    judge_client = OpenAI()
    records_path = out / f"results-{config}.jsonl"
    records_path.unlink(missing_ok=True)
    by_id = {c["id"]: c for c in cases}
    readers = {name: provision.with_db(ADMIN_DSN, f["database"], user=f["reader"], password=READER_PASSWORD)
               for name, f in spec["fixtures"].items()}
    run_meta = {"config": config, "config_sha256": config_sha, "dataset": spec["name"],
                "dataset_version": spec["version"], "dataset_sha256": digest, "git_sha": git_sha(),
                "judge_model": grade.JUDGE_MODEL, "server_trace_project": SERVER_PROJECT,
                "started_at": datetime.now(timezone.utc).isoformat()}

    http = httpx.Client(base_url=API.rstrip("/") + "/", timeout=300)
    api = provision.Api(API, master_key())
    keys = {name: provision.agent_key(api, OWNER, agent["agent_id"]) for name, agent in state["agents"].items()}

    def target(inputs: dict) -> dict:
        case = by_id[inputs["case_id"]]
        agent = state["agents"][case["fixture"]]
        started = time.perf_counter()
        response = http.post(f"v1/agents/{agent['agent_id']}/chat", params={"stream": "false"},
                             headers={"X-API-Key": keys[case["fixture"]]},
                             json={"query": case["question"], "debug_info": True,
                                   "chart_output": bool(case.get("chart")), "follow_up": False})
        client_ms = int((time.perf_counter() - started) * 1000)
        record = {"run_id": str(uuid.uuid4()), "case_id": case["id"], "fixture": case["fixture"],
                  "config": config, "http_status": response.status_code, "client_latency_ms": client_ms}
        if response.is_error:
            record.update(correct=False, error=f"HTTP {response.status_code}")
        else:
            body = response.json()
            usage = body.get("usage") or {}
            debug = body.get("debug_info") or {}
            check = grade.sql_check(debug.get("sql_query"), lambda: closing(psycopg2.connect(readers[case["fixture"]])))
            exact = (grade.exact_table_match(case["expected"]["rows"], debug.get("db_result"), case.get("ordered", False))
                     if case["expected"] else None)
            verdict = grade.judge(judge_client, case, case["expected"], body)
            record.update(
                correct=grade.is_correct(case, verdict), verdict=verdict, exact_table_match=exact,
                sql=check, sql_valid=bool(check.get("executes")), is_answered=body.get("is_answered"),
                server_latency_ms=usage.get("latency_ms"), estimated_cost_usd=usage.get("estimated_cost_usd"),
                cost_complete=usage.get("cost_complete"), price_table=usage.get("price_table"),
                nodes=usage.get("nodes"), config_verified=config_matches(usage, models),
                server_trace_id=body.get("trace_id"), sql_query=debug.get("sql_query"),
                answer=body.get("response"),
                chart_returned=bool((body.get("chart_output") or {}).get("chart_data")))
        with records_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")
        mark = "OK  " if record["correct"] else "FAIL"
        print(f"{mark} {config} {case['id']} {client_ms} ms ${record.get('estimated_cost_usd')}"
              f" verified={record.get('config_verified')}", flush=True)
        return {k: record.get(k) for k in ("correct", "sql_valid", "client_latency_ms", "server_latency_ms",
                                           "estimated_cost_usd", "config_verified", "server_trace_id")}

    if upload:
        from langsmith import Client, evaluate
        client = Client()
        name = f"{spec['name']}-{spec['version']}-{digest[:8]}"
        if client.has_dataset(dataset_name=name):
            dataset = client.read_dataset(dataset_name=name)
        else:
            dataset = client.create_dataset(name, description=f"{spec['about']} sha256 {digest}",
                                            metadata={"dataset_sha256": digest, "version": spec["version"]})
            client.create_examples(
                dataset_id=dataset.id,
                inputs=[{"case_id": c["id"], "question": c["question"], "fixture": c["fixture"]} for c in cases],
                outputs=[{"expected": c["expected"], "supported": c.get("supported", True)} for c in cases],
                metadata=[{"case_id": c["id"], "fixture": c["fixture"]} for c in cases])

        def metric(key):
            def evaluator(outputs: dict) -> dict:
                value = outputs.get(key)
                return {"key": key, "score": float(value) if value is not None else None}
            evaluator.__name__ = key
            return evaluator

        results = evaluate(target, data=name, evaluators=[metric(k) for k in (
            "correct", "sql_valid", "client_latency_ms", "server_latency_ms", "estimated_cost_usd", "config_verified")],
            experiment_prefix=f"{config}-{run_meta['git_sha'][:7]}", metadata=run_meta,
            max_concurrency=0, num_repetitions=repeats, client=client)
        run_meta["langsmith_experiment"] = results.experiment_name
        run_meta["langsmith_dataset"] = name
    else:
        for _ in range(repeats):
            for case in cases:
                target({"case_id": case["id"]})
    run_meta["finished_at"] = datetime.now(timezone.utc).isoformat()
    (out / f"run-{config}.json").write_text(json.dumps(run_meta, indent=2) + "\n", encoding="utf-8")
    records = [json.loads(line) for line in records_path.read_text(encoding="utf-8").splitlines()]
    if not all(r.get("config_verified") for r in records if r.get("http_status") == 200):
        raise SystemExit(f"{config}: some answers were produced by models outside this configuration")


# ── report ──────────────────────────────────────────────────────────────────

def percentile(values, q):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    k = (len(values) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(values) - 1)
    return round(values[lo] + (values[hi] - values[lo]) * (k - lo))


def summarize(records: list) -> dict:
    n = len(records)
    costs = [r.get("estimated_cost_usd") for r in records if r.get("estimated_cost_usd") is not None]
    return {
        "answers": n,
        "correct": sum(bool(r.get("correct")) for r in records),
        "accuracy": round(sum(bool(r.get("correct")) for r in records) / n, 3) if n else None,
        "sql_valid_rate": round(sum(bool(r.get("sql_valid")) for r in records if r.get("sql") and r["sql"].get("present"))
                                / max(1, sum(1 for r in records if r.get("sql") and r["sql"].get("present"))), 3),
        "server_latency_ms_p50": percentile([r.get("server_latency_ms") for r in records], 0.5),
        "server_latency_ms_p95": percentile([r.get("server_latency_ms") for r in records], 0.95),
        "client_latency_ms_p50": percentile([r.get("client_latency_ms") for r in records], 0.5),
        "estimated_cost_usd_mean": round(statistics.mean(costs), 6) if costs else None,
        "estimated_cost_usd_total": round(sum(costs), 6) if costs else None,
        "cost_complete": all(r.get("cost_complete") for r in records if "cost_complete" in r),
        "http_errors": sum(1 for r in records if r.get("http_status") != 200),
    }


def report(out: Path) -> dict:
    configs = sorted(p.stem.removeprefix("results-") for p in out.glob("results-*.jsonl"))
    data = {c: [json.loads(l) for l in (out / f"results-{c}.jsonl").read_text(encoding="utf-8").splitlines()]
            for c in configs}
    summary = {"generated_at": datetime.now(timezone.utc).isoformat(), "configs": {}, "cases": {},
               "judge_exact_disagreements": []}
    for config, records in data.items():
        meta_path = out / f"run-{config}.json"
        summary["configs"][config] = {
            "run": json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else None,
            "overall": summarize(records),
            "by_fixture": {f: summarize([r for r in records if r["fixture"] == f])
                           for f in sorted({r["fixture"] for r in records})}}
        for r in records:
            cell = summary["cases"].setdefault(r["case_id"], {}).setdefault(config, {
                "correct": 0, "answers": 0, "failure_kinds": [], "reasons": []})
            cell["answers"] += 1
            cell["correct"] += bool(r.get("correct"))
            verdict = r.get("verdict") or {}
            if not r.get("correct"):
                cell["failure_kinds"].append(verdict.get("failure_kind") or r.get("error"))
                cell["reasons"].append(verdict.get("reason"))
            if r.get("exact_table_match") is not None and verdict:
                if r["exact_table_match"] != (verdict.get("table_verdict") == "match"):
                    summary["judge_exact_disagreements"].append({
                        "config": config, "case_id": r["case_id"], "exact": r["exact_table_match"],
                        "judge": verdict.get("table_verdict"), "reason": verdict.get("reason")})
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")
    (out / "summary.md").write_text(markdown(summary), encoding="utf-8")
    return summary


def markdown(summary: dict) -> str:
    configs = list(summary["configs"])
    lines = ["# Database Agent model evaluation", "",
             "| Config | Accuracy | SQL valid | p50 latency | p95 latency | Mean est. cost | Total est. cost |",
             "|---|---|---|---|---|---|---|"]
    for c in configs:
        o = summary["configs"][c]["overall"]
        lines.append(f"| {c} | {o['correct']}/{o['answers']} ({o['accuracy']:.0%}) | {o['sql_valid_rate']:.0%} | "
                     f"{(o['server_latency_ms_p50'] or 0) / 1000:.1f} s | {(o['server_latency_ms_p95'] or 0) / 1000:.1f} s | "
                     f"${o['estimated_cost_usd_mean'] or 0:.4f} | ${o['estimated_cost_usd_total'] or 0:.4f} |")
    lines += ["", "| Case | " + " | ".join(configs) + " |", "|---|" + "---|" * len(configs)]
    for case, cells in summary["cases"].items():
        row = []
        for c in configs:
            cell = cells.get(c)
            if not cell:
                row.append("-")
                continue
            text = f"{cell['correct']}/{cell['answers']}"
            if cell["failure_kinds"]:
                text += " " + ", ".join(sorted({str(k) for k in cell["failure_kinds"]}))
            row.append(text)
        lines.append(f"| {case} | " + " | ".join(row) + " |")
    if summary["judge_exact_disagreements"]:
        lines += ["", f"Judge and exact-match disagreed on {len(summary['judge_exact_disagreements'])} answers (see summary.json)."]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["prepare", "ask", "report"])
    parser.add_argument("--out", type=Path, default=Path(os.getenv("MODEL_EVAL_OUT", "/results")))
    parser.add_argument("--config")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--no-upload", action="store_true", help="do not create a LangSmith experiment")
    options = parser.parse_args()
    if options.command == "prepare":
        prepare(options.out)
    elif options.command == "ask":
        if not options.config:
            raise SystemExit("--config is required")
        ask(options.out, options.config, options.repeats, upload=not options.no_upload)
    else:
        print(markdown(report(options.out)))


if __name__ == "__main__":
    main()
