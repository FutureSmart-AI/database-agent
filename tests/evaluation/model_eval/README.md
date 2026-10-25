# Model evaluation

Compares model configurations on accuracy, SQL validity, latency and cost by asking real
questions through the product's own chat API, with the real model pipeline, against two
synthetic databases. Nothing here is a separate or simplified SQL agent.

## What is measured, per answer

| Measure | How |
| --- | --- |
| Correct | LLM judge (`gpt-6.1-sol`, structured verdict with reason and failure kind) compares the returned rows and prose answer with ground truth. Correct = rows match **and** the answer is correct; for an unanswerable question, correct = declines without inventing values. |
| Exact table match | Mechanical evidence beside the verdict: the expected columns are found among the returned ones, row for row, at the reference's precision. Disagreements with the judge are listed in the report for review. |
| SQL valid | The returned SQL parses as one read-only SELECT and executes on the evaluation database as the read-only role. |
| Latency | `usage.latency_ms` from the API (agent processing time) and the client's wall time. |
| Cost | `usage.estimated_cost_usd` from the API: each node's recorded tokens times the dated list prices in `backend/model_profiles/prices.json` (cached input at the cached rate). An unpriced model makes `cost_complete` false. |
| Config verified | The models the API reports per node must belong to the configuration under test; otherwise the run fails. |

Ground truth is computed twice — by each fixture's builder in Python and by its reference
SQL on the loaded database — and `prepare` stops unless the two agree.

## Data

`dataset.json` (versioned; its SHA-256 covers the dataset, builders, agent definitions and
references) has 18 cases:

- **ecommerce** — Cedar Lane, the hosted sample-data agent's database (`deploy/demo/ecommerce`):
  8 reference questions (one asks for a chart) and one unanswerable question.
- **clinic** — Riverbend Clinics (`fixtures/clinic`): a structurally different schema with a
  many-to-many clinician/location table, shifts vs appointments at different grains, invoices
  paid in partial payments, and patients known only through appointments. 8 questions and one
  unanswerable question.

Both agents are created through the API exactly like the hosted demo agent: business
definitions as table descriptions, every table visible, no template.

## Configurations

`configs/<name>.json` are ordinary `model_config.json` files. `recommended-v1` is the shipped
profile; `luna-low-v1` moves database routing, table selection, SQL generation and pandas
planning from `gpt-6.1-sol` to `gpt-6-luna` (Responses, reasoning low, the same 8,192-token
output cap). Add a file to evaluate another configuration; OpenAI model IDs must be available
to the evaluation key.

## Running

On demand or weekly (Monday 02:30 UTC) in GitHub Actions: **Model evaluation** workflow,
inputs `configs` and `repeats`. It needs the repository secrets `MODEL_EVAL_OPENAI_API_KEY`
and `MODEL_EVAL_LANGSMITH_API_KEY`. The run's artifact holds `results-<config>.jsonl` (every
answer, SQL, rows-check, verdict, per-node usage), `run-<config>.json` (config/dataset hashes,
git SHA, LangSmith experiment) and `summary.json` / `summary.md`.

Locally, with Docker and the same two keys in the environment:

```sh
python deploy/configure.py            # once
C="docker compose -f compose.yaml -f tests/evaluation/model_eval/compose.yaml"
$C build api
$C --profile eval up -d --wait metadata-db sample-db qdrant eval-db && $C run --rm bootstrap
MODEL_EVAL_CONFIG=recommended-v1 $C up -d --force-recreate --no-deps --wait api
$C --profile eval run --rm --no-deps model-eval prepare
$C --profile eval run --rm --no-deps model-eval ask --config recommended-v1 --repeats 2
MODEL_EVAL_CONFIG=luna-low-v1 $C up -d --force-recreate --no-deps --wait api
$C --profile eval run --rm --no-deps model-eval ask --config luna-low-v1 --repeats 2
$C --profile eval run --rm --no-deps model-eval report
```

LangSmith: the dataset is `database-agent-model-eval-v1-<sha8>` (a content change creates a
new one); each `ask` is an experiment named `<config>-<git sha>` with per-answer feedback
(`correct`, `sql_valid`, latencies, cost); the API's own graph traces go to project
`database-agent-model-eval-server` and are linked from each answer by `server_trace_id`.

A single run is evidence about these 18 questions, not a production decision: change the
shipped profile only after repeated runs and a review of the failures.

Offline checks: `python -m unittest discover -s tests/evaluation -p test_model_eval.py`.
