# Development and checks

Start with the root README. Docker uses the frozen `backend/requirements.txt`
and `frontend/bun.lock`; no sibling checkout is needed.

```sh
docker compose run --rm -v "${PWD}/tests:/tests:ro" api python /tests/run.py
python -m unittest discover -s tests/deployment -v
docker compose run --rm evaluate --fixture-only
```

Deployment checks use only Python's standard library. Fixture-only verification
checks known SQL results and read-only grants without a model call. With
runtime provider keys and the API running:

```sh
docker compose run --rm evaluate
```

This evaluation creates an agent through the direct API, connects the synthetic
source, issues an agent key, and asks one real model question. It independently
executes the SQL and checks returned rows and answer against North=250 and
South=200. It does not request a chart; verify that through the README UI flow.
The smoke now compares complete typed API rows to independently executed SQL,
including entity/value association, row order and multiplicity. Its English
two-region amount checker accepts a limited set of formats: unrecognized prose
raises `UnsupportedAnswerFormat` for manual review, not a model factual verdict.
It rejects contradictory units/amounts rather than independent number substrings.
See the [numeric and answer policy](../tests/evaluation/reliability/fixtures/v1/RULES.md).
The unavailable-validator control also has a bounded grammar: a trusted case
subject (`Review ratings` or `Ratings` by default), `is/are`, then `unavailable`,
`not available` or `not supported`, optionally `in this schema` and punctuation.
It permits one sentence only. Negated unavailability, extra invented ratings
(including spelled-out numbers) and other prose require manual review through
`UnsupportedAnswerFormat`. This does not infer a model's schema-support decision.
Currency prefixes and signed/accounting formats whose signs are not part of the
parsed number also require manual review; parentheses are treated as ambiguous.

## Provider-free evaluator reliability checks

The separate versioned fixture has four tables/29 source rows, fixed January2026
rules and a February1 as-of. The installation sample stays unchanged. Nine
positive validator/reference controls and20 deliberately wrong SQL controls
cover population, join cardinality, status/date/refund/currency/denominator
errors, zero versus NULL/unavailable, and complete55-row results.

```sh
python -m pip install sqlglot==26.14.0
python -m unittest discover -s tests/evaluation -p test_reliability.py -v
python tests/evaluation/check_reliability.py --backend sqlite --report sqlite-results.json
```

SQLite is an in-memory fast check, not PostgreSQL proof. The bounded CI
`evaluation-reliability` job executes the same references and successful wrong
queries on a fresh PostgreSQL16.6 service. Full synthetic SQL/rows/reasons are
retained in its artifact. No application/provider credentials or model calls.
The PostgreSQL schema/data are transactional and rolled back; the CI service is
discarded. Do not point this at an existing application database.

For an explicitly disposable local reproduction (after installing the pinned
`psycopg2-binary==2.9.13` test driver):

```sh
docker run --rm --name da-eval-reliability -d -p 127.0.0.1:15439:5432 \
  -e POSTGRES_USER=eval_fixture_admin -e POSTGRES_PASSWORD=synthetic-ci-only \
  -e POSTGRES_DB=eval_reliability postgres:16.6-alpine
# Wait for: docker exec da-eval-reliability pg_isready -U eval_fixture_admin -d eval_reliability
EVAL_RELIABILITY_DISPOSABLE=1 EVAL_RELIABILITY_PORT=15439 \
  python tests/evaluation/check_reliability.py --backend postgres --report postgres-results.json
docker stop da-eval-reliability
```

The runner fixes loopback, database/user and synthetic credential; only the test
port and disposable opt-in are accepted. There is no DSN/env-file fallback. It
uses3s connect/2s statement/1s lock timeouts. PowerShell users set the two
`$env:EVAL_RELIABILITY_*` variables separately before the Python command.
Existing containers, volumes, production/provider requests and accuracy ledgers
are outside these instructions.

This verifies evaluators and fixture business arithmetic, not model accuracy,
API/UI behavior, unseen generalization or upgraded historical benchmark verdicts.
Goldens/reference SQL are public regression assets, never application prompts
or examples. See [rules and derivation](../tests/evaluation/reliability/fixtures/v1/RULES.md)
and the [versioned byte/content manifest](../tests/evaluation/reliability/fixtures/v1/manifest.json).

Small SQL fixtures in `tests/accuracy/fixtures/` retain existing regressions.
Historical benchmark suites are outside the installation.

For backend development use Python 3.11, install `backend/requirements.txt`, and
run from `backend/` with reachable metadata/vector settings:

```sh
python -m standalone.bootstrap
uvicorn main:app --host 127.0.0.1 --port 18000
```

Container hostnames must resolve from that process; prefer Compose unless you
configure reachable services. Bootstrap creates a fresh standalone baseline
and applies Alembic migrations. For an existing managed database, inspect
migration state and deliberately run `alembic upgrade head`; do not bootstrap
or stamp an arbitrary database.

For UI development use Bun 1.4.0 from `frontend/`:

```sh
bun install --frozen-lockfile
# Copy .env.example to .env.local, then:
bun run dev
bun x vitest run src/data/__tests__/serviceBoundary.test.ts src/components/home/__tests__/NewAgentWizard.test.tsx
```

The dev proxy points to API port 18000. On Windows use a short checkout path
to avoid native source-map path limits. Container builds use `/app`.

CI builds both images, initializes fresh metadata twice, runs focused checks,
and starts UI/API without provider calls. It scans the actual tracked tree
and verifies relocation preserves application, prompts, models, migrations,
and UI. It publishes no images and deploys no service.

## Research-driven changes

Update the [improvement history](improvements/README.md) with each relevant
change or declined capability. Follow the [maintenance protocol](improvements/MAINTAINING.md);
preserve original verdicts, explicit unknowns, fixture/version identity and
separate implementation from independent benchmark and production acceptance.
Do not copy private research into the public history.
