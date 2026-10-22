# S64: Unsupported data was reported as zero

Retrospective case study, documented 22 October 2026 IST. Engineering record:
[DA-001](history.md#da-001-unsupported-data-must-not-become-a-false-zero). This document explains an existing released correction;
it does not implement a new fix or report a new benchmark run.

| Status | Recorded outcome |
|---|---|
| Original AI Demos result | **Fail — unchanged**; one failed test case |
| Engineering correction | **Released**, recorded 20 October 2026 IST |
| Independent engineering validation | Recorded staging/production controls passed, within the limits below |
| Independently accepted S64 benchmark retest | **Pending**; no new benchmark Pass is claimed |

## The published finding

The [original AI Demos result](https://aidemos.com/benchmarks/ai-database-agents/results/futuresmart-ai-database-agent/the-connected-data-cannot-answer-the-question)
concerns a connected dataset that did not support the requested topic. The user asked:

> How many 5-star reviews have we received this month?

The product used `action_log` and returned zero instead of explaining that the
available data could not answer the question. The published expectation was an
unavailable answer with no number. The page records **Fail**, with a screenshot
showing the question, answer, returned row and SQL panel. See the
[original public proof](https://aidemos.com/benchmarks/ai-database-agents/results/futuresmart-ai-database-agent/the-connected-data-cannot-answer-the-question#proof-3fd7d42ff0a3).

The page dates the evidence to **8 September 2026**, its grade to **12 October**,
and first publication to **21 October**. It identifies Cedarline commerce
`customer_support_db`, version 1; the original hosted build was not exposed,
and the original model is unknown. The engineering record is dated **20 October**:
research informed the correction before that finding was publicly published.
This is a retrospective connection, not a claim that a public issue or PR
initiated the historical work.

## What went wrong, and the decision

The [approved maintainer record](records.json) diagnoses a semantic support gap:
a query could execute successfully against an available table even though that
table did not represent the requested business metric. An aggregate result of
zero then looked like a factual answer. Successful SQL execution alone does not
establish that the schema supports the question. That is the recorded engineering
diagnosis, not a reconstruction of the unknown historical hosted build.

The decision was to require an explicit schema-support decision and preserve
three different outcomes:

| Outcome | Meaning and required behavior |
|---|---|
| Supported metric, result zero | A valid query against the right data returned zero. Keep that answer. |
| Unsupported metric | The available schema does not establish the requested information. Explain unavailability; do not substitute a proxy table or number. |
| Restricted data or execution failure | Preserve the access denial or query error; neither establishes zero or universal data absence. |

## How the released code carries that decision

These links point to actual code already present in this public repository;
this documentation change does not alter it.

1. [SQL-generation instructions](../../backend/agent/utils/prompts.py#L186) require
   schema support before generating SQL, reject unrelated proxies, and preserve
   legitimate zero aggregates.
2. [SQLQuerySchema and apply_sql_decision](../../backend/agent/utils/answerability.py#L5)
   require a strict Boolean `answerable` decision. Missing or malformed decisions
   cannot approve SQL. An explicit unsupported decision clears surrogate SQL and
   stale rows, sets an answerability error, and returns no query. A supported
   decision must contain a nonempty query.
3. [SQL generation](../../backend/agent/nodes/sql_gen.py#L553) applies that decision;
   [SQL execution](../../backend/agent/nodes/sql_exec.py#L55) returns before database
   execution when an answerability error is present. Existing table-access guards
   remain separate.
4. [Final-answer handling](../../backend/agent/nodes/final_answer.py#L149) uses
   [failure_response](../../backend/agent/utils/answerability.py#L30) before invoking
   the presentation model. Unsupported input yields `is_answered=false`, cleared
   result/chart state, and an explanation that no count of zero was established.
5. [Cross-database merging](../../backend/agent/nodes/cross_db_merge.py#L95) retains
   unavailability when all required subresults are unsupported. Mixed required-source
   outcomes retain the combination/error contract rather than asserting absence
   across every database.

The [public initial commit](https://github.com/FutureSmart-AI/database-agent/commit/37922276843b0db86c275b786d56db6dd322c3f4)
already contains this behavior. DA-001 retains historical implementation
identifiers `174b06e` and `97fdcf4`; those private commits and their development
history were not imported. They are not public fix commits or evidence of a
historical public issue/PR. The current documentation PR is retrospective only.

## Regression controls and recorded independent validation

The existing [answerability regression tests](../../tests/backend/test_answerability.py)
cover these boundaries with mocked database/model calls:

| Existing control | Contract checked |
|---|---|
| `test_missing_schema_discards_surrogate_sql_and_stale_rows` | Unsupported decisions cannot retain proxy SQL or old results. |
| `test_correct_count_query_is_not_rejected_based_on_its_result` and `test_valid_zero_reaches_database_and_remains_answerable` | Genuine zero and positive counts remain supported; zero is not an abstention heuristic. |
| `test_missing_or_malformed_support_decision_cannot_approve_raw_sql` | Missing decisions, string Booleans and empty supported SQL fail validation. |
| `test_unsupported_sql_never_reaches_database_or_final_answer_model` | Explicit unsupported state skips source execution and presentation-model work. |
| `test_existing_table_guard_still_blocks_before_execution` and `test_malformed_sql_and_unavailable_connection_do_not_become_zero` | Restrictions, syntax errors and connection failures do not become numerical answers. |
| Both cross-database tests in `PipelineTests` | All-unsupported and mixed required-source outcomes remain distinct. |

The [synthetic answerability fixture](../../tests/accuracy/fixtures/answerability.sql)
contains products, orders and administrative activity events, rather than a review
dataset. It is a regression asset, not a reconstruction of the original database.

The pre-existing [DA-001 history](history.md#da-001-unsupported-data-must-not-become-a-false-zero) records independent staged
browser controls for missing data, a real count of zero and a count of two; it
also records a production missing-data check and a separate real-source positive
SQL/rows/chart check. These are **recorded historical engineering validations**.
Their operator receipts are not published here, and they are not a new independent
S64 benchmark retest. Preparing this retrospective did not rerun those historical controls or request
a new model or benchmark evaluation. Routine documentation and packaging checks
do not constitute a benchmark retest.

## Limits and the remaining benchmark gate

The correction carries an explicit support decision through the pipeline; it does
not prove that a model will always classify every schema and question correctly.
Metadata/schema-hint omissions remain separate. The current public source also
contains later changes, so it cannot identify the unknown original hosted build.

An independently accepted benchmark retest remains **pending**. Such a retest
would need a pinned newer build/configuration, an appropriate bound dataset and
independent grading of the original behavior, with genuine-zero controls. This
case study does not schedule or execute it. The original **Fail** remains visible
and unchanged; a released engineering correction, regression tests, or green CI
does not turn that historical result into Pass.
