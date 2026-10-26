# Database Agent: engineering history

Documented 2026-10-21 (IST); earlier dates are dates supported by the saved work records.

| Entry | Recorded date (IST) | State |
| --- | --- | --- |
| [DA-001: Unsupported data must not become a false zero](#da-001) | 2026-10-20 | released |
| [DA-002: Render nested stacked-chart results without losing series](#da-002) | 2026-10-20 | released |
| [DA-003: Preserve metric meaning when changing scope](#da-003) | 2026-10-20 | candidate_unaccepted |
| [DA-004: Deliver and save the primary answer before optional work](#da-004) | 2026-10-20 | candidate_unaccepted |
| [DA-005: Preserve a complete installable reference application](#da-005) | 2026-10-20 | source_accepted |
| [DA-006: Evaluate speed together with correctness](#da-006) | 2026-10-20 | evaluation_only |
| [DA-007: Reject false-positive evaluation results](#da-007) | 2026-10-21 | evaluation_only |
| [DA-008: Verify table access before reading source data](#da-008) | 2026-10-21 | source_accepted |
| [DA-DEC-001: Core capability quality takes precedence over commercial feature parity](#da-dec-001) | 2026-10-21 | deferred |

<a id="da-001"></a>
## DA-001: Unsupported data must not become a false zero

Recorded date: **2026-10-20 IST**. State: **released**.

[Read the complete S64 retrospective](S64-unsupported-data.md): finding → code/tests → recorded validation. Original **Fail unchanged**; independently accepted benchmark retest **pending**.

**Research source.** The [unsupported-data Result](https://aidemos.com/benchmarks/ai-database-agents/results/futuresmart-ai-database-agent/the-connected-data-cannot-answer-the-question) is now published. Our later reproduction and validation remain separate from that historical run.

**Original benchmark result.** Published **Fail**, unchanged. The released fix below does not regrade that run.

**Failure or limitation.** An unsupported reviews question was answered with zero using unrelated audit records.

**Root cause and uncertainty.** SQL could run on an available table even when that table did not represent the requested metric. Query success was mistaken for answer support.

**Engineering decision.** Require an explicit schema-support decision. Keep genuine zero distinct from unavailable data; preserve table-access and execution-error guards.

**Implementation.** Added answerability propagation through SQL generation/execution, final answer and multi-source paths. Clear surrogate SQL/stale rows when unsupported.

**Validation evidence.** Focused regressions cover unsupported input, real zero, positive results, denied tables and execution errors. Independent staged browser controls covered missing data, count 0 and count 2; a production missing-data check and a separate real-source positive SQL/rows/chart check passed.

**Limits and what remains unproved.** A bounded product fix, not a full historical benchmark rerun. Metadata/schema-hint omissions remain separate. The original research verdict is not changed.

Recorded source identifiers: `174b06e`, `97fdcf4`.

- [backend/agent/utils/answerability.py](../../backend/agent/utils/answerability.py)
- [tests/backend/test_answerability.py](../../tests/backend/test_answerability.py)
- [tests/accuracy/fixtures/answerability.sql](../../tests/accuracy/fixtures/answerability.sql)

<a id="da-002"></a>
## DA-002: Render nested stacked-chart results without losing series

Recorded date: **2026-10-20 IST**. State: **released**.

**Research source.** Published charting context: https://aidemos.com/tools/futuresmart-ai-database-agent. The exact nested-renderer defect was a separate maintainer reproduction.

**Original benchmark result.** Published Automatic Chart Generation: Partial, unchanged; exact nested-renderer scenario is not the published historical test

**Failure or limitation.** A valid nested stacked-chart response could be unavailable in the UI despite valid SQL/rows and stored chart data.

**Root cause and uncertainty.** The frontend result contract did not consistently normalize flat and nested segmented chart shapes.

**Engineering decision.** Normalize the supplied result contract; keep individual values, zeros, missing series and Data/Query/Raw views. Do not replace SQL or tune a model to repair a renderer.

**Implementation.** Updated typed chart normalization and stacked-bar rendering for live and saved conversations.

**Validation evidence.** Component contracts and independent staged/production browser checks passed. A synthetic four-order source produced visible North 100+150 and South 80+120 segments; SQL, all rows and full-reload saved reopen agreed.

**Limits and what remains unproved.** This fixes rendering. It does not prove that a chart-only follow-up preserves the original business metric, or upgrade the published broad charting result.

Recorded source identifiers: `83c0727`, `837dbb1`.

- [frontend/src/components/conversations/__tests__/stackedContract.test.tsx](../../frontend/src/components/conversations/__tests__/stackedContract.test.tsx)
- [frontend/src/data/__tests__/nl2sqlChat.test.ts](../../frontend/src/data/__tests__/nl2sqlChat.test.ts)

<a id="da-003"></a>
## DA-003: Preserve metric meaning when changing scope

Recorded date: **2026-10-20 IST**. State: **candidate_unaccepted**.

**Research source.** Unpublished researcher feedback retained privately; published follow-up context is linked in baseline.md.

**Original benchmark result.** Not publicly verifiable: case-level source is unpublished; no new benchmark verdict

**Failure or limitation.** Maintainer replays found numerator/population and scope inconsistencies; a plausible percentage could represent a different question.

**Root cause and uncertainty.** Metric definition, denominator population and follow-up scope were not consistently preserved. Exact historical deployed configuration is unknown.

**Engineering decision.** Keep numerator/denominator and scope guards explicit. Compare to reference SQL on the same data state; never force historical numeric literals onto a changed database.

**Implementation.** A separate candidate adds metric/scope consistency checks; it remains outside the accepted main application.

**Validation evidence.** Native pair/grouped controls passed after earlier wrong results were retained. Remaining semantic controls, independent candidate browser acceptance and production proof are incomplete.

**Limits and what remains unproved.** No release or historical benchmark Pass. This candidate is separate from the delivery work.

Recorded source identifiers: `08d8388`.


<a id="da-004"></a>
## DA-004: Deliver and save the primary answer before optional work

Recorded date: **2026-10-20 IST**. State: **candidate_unaccepted**.

**Research source.** Maintainer-observed timeout/empty initial UI and measured request-path investigation; no published case-level research result established.

**Original benchmark result.** Not publicly verifiable: case-level source is unpublished; no new benchmark verdict

**Failure or limitation.** The old request waited for the whole graph/chart before its first useful answer. Later transport errors could erase an already received answer or identity.

**Root cause and uncertainty.** Required answer delivery, optional work, persistence acknowledgement and frontend error state shared one fragile completion boundary.

**Engineering decision.** Use one owned request lifecycle; publish an immutable validated primary after existing guards, acknowledge one insert, and scope optional updates by actual row and authorized ownership. Never retry an insert after unknown commit.

**Implementation.** A separate candidate implements primary-before-optional delivery, scoped persistence, retained frontend identity/answer, bounded cancellation and saved-answer-status replay. It does not change models or hosted edge timeouts.

**Validation evidence.** On one independent real-provider synthetic sales turn, saved answer arrived 10.922 seconds, chart/EOF 14.500 seconds; complete two rows and saved reopen matched the source. Six native lifecycle contracts passed with declared upstream stubs/no provider calls. A native TCP-reset UI check retained the answer and obtained SQL/rows via one automatic saved read.

**Limits and what remains unproved.** These timings are not a before/after speed comparison, p95 or SaaS accuracy result. With debug disabled, primary wire has no SQL/rows; they reconcile from storage. The reset proxy cannot exclude coalesced later frames, so exclusive-primary-only delivery is not claimed. Final saved-status correction has green CI but independent replay is incomplete. No production promotion.

Recorded source identifiers: `356b679`, `adc7098`.


<a id="da-005"></a>
## DA-005: Preserve a complete installable reference application

Recorded date: **2026-10-20 IST**. State: **source_accepted**.

**Research source.** Maintainer installation/repository review, not a benchmark accuracy case.

**Original benchmark result.** Not publicly verifiable: case-level source is unpublished; no new benchmark verdict

**Failure or limitation.** A working service repository was still cluttered and depended on deployment knowledge rather than a clear complete-product installation.

**Root cause and uncertainty.** Product source, installation assets and internal operational material were mixed.

**Engineering decision.** Keep backend, UI, supported deployment, sample and guides in one opinionated repository. Preserve existing behavior; keep private operational history out of distributable builds.

**Implementation.** Reorganized source and added a supported one-clone installation and deployment documentation.

**Validation evidence.** Fresh-checkout build, UI/API sample checks and restart/persistence were independently checked. The then-known chart limitation was recorded and fixed separately in DA-002.

**Limits and what remains unproved.** Installability is not general answer accuracy, public licensing, or proven load capacity.

Recorded source identifiers: `a33c37d`.

- [README.md](../../README.md)
- [docs/development.md](../../docs/development.md)
- [docs/architecture.md](../../docs/architecture.md)

<a id="da-006"></a>
## DA-006: Evaluate speed together with correctness

Recorded date: **2026-10-20 IST**. State: **evaluation_only**.

**Research source.** Maintainer operation timings and separately controlled local evaluations; unpublished dataset/context details stay private.

**Original benchmark result.** Not publicly verifiable: case-level source is unpublished; no new benchmark verdict

**Failure or limitation.** Faster responses could contain wrong SQL, wrong populations or unsupported units, while some provider requests were rejected.

**Root cause and uncertainty.** Two production observations spent 37.083 s of 43.037 s and 72.556 s of 83.958 s in SQL generation, with SQL execution of 0.029 s / 0.030 s. This does not isolate a universal provider cause.

**Engineering decision.** Compare complete typed rows to pinned business definitions, use finite call budgets and retain every refusal/wrong result. Do not choose a model from speed alone or claim unverified remote experiment persistence.

**Implementation.** Separate evaluation code and sanitized local result records were prepared; no winning model was adopted.

**Validation evidence.** Reviewed complete SQL/results and local evaluator feedback; no accepted quality winner. Remote experiment persistence remained unverified after rate limits; polling stopped.

**Limits and what remains unproved.** No cost-saving, TTFT, p95, generic model-capability, or broad accuracy claim; failed screens remain failed.

Recorded source identifiers: `c2a7f24`.


<a id="da-dec-001"></a>
## DA-DEC-001: Core capability quality takes precedence over commercial feature parity

Recorded date: **2026-10-21 IST**. State: **deferred**.

**Research source.** Project-purpose decision from the maintainer; recorded in the README.

**Original benchmark result.** Not publicly verifiable: case-level source is unpublished; no new benchmark verdict

**Failure or limitation.** Treating every capability row as a feature promise would replace a dependable reference application with an unbounded commercial roadmap.

**Root cause and uncertainty.** Capability availability, correctness, usability and measurement are different evaluation dimensions.

**Engineering decision.** Prioritize correct SQL/results, inspectability, reproducibility and usable deployment. Generalized multi-tenant controls, billing expansion and feature-for-feature SaaS competition are outside the current objective.

**Implementation.** Documentation decision only; no runtime capability removed or implied to exist.

**Validation evidence.** Reviewed against the existing product boundary and this history. Missing capabilities retain their original private verdicts.

**Limits and what remains unproved.** Deferred capabilities do not become benchmark Pass results or disappear from the private baseline.


## Public validation summary

[Sanitized independent synthetic delivery result](evidence/2026-10-20-synthetic-delivery.json)
contains only the committed sample fixture totals, complete typed result, measured
phase times and limits. Session IDs, private endpoints, accounts and runtime
credentials are omitted. Original private receipts are retained separately.

<a id="da-007"></a>
## DA-007: Reject false-positive evaluation results

Recorded date: **2026-10-21 IST**. State: **evaluation_only; independently verified source; no application release/deployment**.

**Research source.** Maintainer-owned synthetic checker investigation with the
existing installation sample. No unpublished benchmark or competitor material.

**Original result.** Swapped North/South totals and tenfold-wrong API/prose values
passed the former manual smoke checker with a correct SQL replay. The original
counterexample remains preserved; no historical benchmark verdict is upgraded.

**Root cause.** Independent substrings were insufficient to associate entities,
amounts, units and complete returned rows.

**Engineering decision and implementation.** Replace those checks with complete
typed-result contracts and a narrow fail-closed two-region narrative checker.
Specify order, multiplicity, finite Decimal/rounding/tolerance/NULL/boolean/unit
policies. Keep the four-order install sample unchanged; separately version a
four-table29-row relational fixture with independently written rules, reference
SQL and complete expected rows. Keep goldens out of application prompts and
examples; public regressions are not claimed as unseen model evaluation.

**Validation.** Local focused checks execute the actual smoke verifier and real
SQLite fixture SQL, including positive controls and deliberately wrong join,
population, status, refund/date, denominator, unit and partial-row outputs.
Nine positive fixture/validator controls and20 successful wrong SQL queries are
discriminating; their wrong outputs are rejected. Fourteen focused tests cover
wire shape, association, multiplicity, order, numeric edge cases and limited
narrative formats. PostgreSQL16.6 CI39562779144 at d3400a3 passed the same
eight reference SQL/one authored support-validator controls and20 wrong SQL
controls, with matching content fingerprint and verified schema rollback.
Candidate self-review then found currency-prefix and ambiguous signed/accounting
formats could be accepted; that candidate failure is retained privately and the
parser now rejects those forms. Independent review also found negated
unavailability and an invented spelled-out rating passed a keyword check. The
original candidate observations remain preserved; a trusted-subject single-
sentence grammar now sends those ambiguous/extra claims to manual review.
Exact revised source `60dca9be68eba7834979014cd04d20e2d2bfe4da` passed
full CI39563484302 including the19-second PostgreSQL reliability job and the
existing source/build/bootstrap/startup checks. Independent review procedurally
recomputed all eight supported reference outputs and passed14 tests plus28 independent checks (6 positive,22 adverse) after returning and verifying the candidate corrections.
The earlier d340 failures and original pre-fix oracle witness remain preserved.

**Limits.** This changes evaluation only, not product inference or UI behavior.
A correct unrecognized narrative requires manual review via
`UnsupportedAnswerFormat`; it is not declared a factual model error. An empty
cohort's NULL rate differs from genuine zero and missing-schema unavailability.
The unsupported control is a validator input, not a model abstention result.
A finite fixture match is not general SQL semantic equivalence, model accuracy,
API/UI proof or a release. No providers, models, prompts, production defaults or
historical verdicts changed; delivery/readiness work remains separate.

- [Rules and independent arithmetic](../../tests/evaluation/reliability/fixtures/v1/RULES.md)
- [Pinned schema/data/reference/expected/content hashes](../../tests/evaluation/reliability/fixtures/v1/manifest.json)
- [Oracle and actual SQL regressions](../../tests/evaluation/test_reliability.py)
- [Reproduction instructions](../development.md#provider-free-evaluator-reliability-checks)


<a id="da-008"></a>
## DA-008: Verify table access before reading source data

Recorded date: **2026-10-21 IST**. State: **source_accepted**.

**Research source and original verdict.** The published [excluded-table Result](https://aidemos.com/benchmarks/ai-database-agents/results/futuresmart-ai-database-agent/an-excluded-table-is-needed-to-answer-the-question)
is **Fail**, unchanged: the product refused but still queried the excluded returns
table and displayed SQL/zero. The wording-to-status mismatch is a separate finding.
All17 published Results, including passing controls, are linked in
[published-results.md](published-results.md); no aggregate accuracy score is inferred.

**Source finding.** Existing main6bed0c27 already has a pre-execution guard for
excluded direct/join reads. However, global CTE-name subtraction can hide a
schema-qualified physical table. Missing/failed/malformed policy can be treated
as unrestricted, and selected-table schema preparation can sample source rows
before the execution-time guard. This is source evidence, not a claim of a new
production exploit or reconstruction of the historical deployed build.

**Verified synthetic reproduction.** Complete original SQL-execution node and
policy function bodies were exercised with synthetic policy records and executor
spies (decorators/application bootstrap omitted). Direct exclusions stopped;
qualified CTE collision, missing policy and failed lookup reached the executor.
An independent reviewer also reproduced these gaps using in-memory SQLite.
No real source database, provider, model or production data was used.

**Implementation.** The accepted source validates a nonempty strict-boolean policy bound
to the actual agent/database before source schema sampling and again before SQL
execution. An all-true verified map is explicit no-exclusions; absent/empty/unknown
policy is not a grant. Newly unconfigured tables require policy refresh. CTEs are
resolved per scope, including qualified/outer references. Policy denials clear
SQL, stale rows and chart state, avoid retries and propagate through required
cross-database sides to an explicit unanswered response.

**Validation and acceptance.** New focused controls exercise denied direct/join,
nested/scoped/qualified CTEs, malformed and unavailable policy, wrong identity,
changed policy, unknown tables and failed parser. Positives execute complete
in-memory SQLite rows for permitted queries, harmless CTEs, genuine zero and a
verified all-included map; source sampling retains permitted tables only.
Independent review found that the first candidate turned a generation denial into
a retryable empty-SQL error at the next node. That failed composition is retained;
the correction preserves denial through actual generation, execution and both
routing functions. Eleven focused methods now pass locally. The initial focused
CI passed, while its full job stopped on separately corrected source-preservation
hashes. Independent source/synthetic review passed on a95608d, including13 reviewer SQL
controls. Full container CI then exposed a test-only checkout-versus-/app source
path error before the policy executed. Explicit layout selection and a focused
path discriminator correct it; twelve local focused methods pass. The next container
run passed36 backend tests, then exposed a legacy positive control reusing mutated
denial state; that separate request fixture now starts from the original input.
The application denial remains terminal.

**Independent acceptance and deployment.** Scoped source/synthetic acceptance was
recorded21 October2026 at18:46IST for `562db709d15511cfdffb3cd3ac5c4fe664e10929`.
Exact-head CI39605744198 (historical private identifier 39605744198; original link omitted)
passed every required job, including image build, source/private boundaries,
fresh bootstrap, backend regressions, fixture evaluation and product startup.
Independent controls verified13 SQL cases (9 denied executor-zero,4 complete-row
or true-zero positives), terminal main/crossDB denial composition, source layouts
and the legacy fresh-request control. This is acceptance for source integration;
final documentation/integration closeout is separate. **Not deployed**. No new
historical benchmark run or verdict change.

**Limits.** This is not a general SQL sandbox; source grants must remain read-only.
Visibility configuration uses normalized bare table names and cannot express an
independent grant for equal names across schemas. Policy reload at each boundary
does not establish atomic revocation during an in-flight source call. Dedicated
setup/profiling endpoints and underlying view/function access are not expanded
into a new authorization system in this issue. Original Fail remains unchanged;
synthetic regressions, CI, source acceptance and deployment are separate stages.

- [Table policy and scoped references](../../backend/agent/utils/table_access.py)
- [Before-sampling policy gate](../../backend/agent/nodes/sql_gen.py)
- [Before-execution policy gate](../../backend/agent/nodes/sql_exec.py)
- [Focused synthetic boundary controls](../../tests/backend/test_access_policy.py)

## DA-009 — One provider for default model operations

2026-10-21 IST. Candidate unaccepted end to end; no benchmark verdict changed.
The source candidate uses OpenAI Sol/Luna operation defaults and compatible
Responses/Chat endpoints, preserving prompts, structured schemas and embedding
vectors. A narrowly extracted pre-sampling policy fails closed before source
rows or SQL-model dispatch; its legacy release lane accepts exact integer0/1
flags without weakening current strict access-policy semantics.

Offline SDK controls, independent emitted-node boundary challenges and required
CI passed. The first CI run's new test-only checkout/image path failure is
preserved, with a resolver correction. The controlled192 deployment became
healthy, but the first API query returned500 after4.5s: the router's OpenAI call
was denied gpt-6-luna with model_not_found. SQL generation and charting were not
reached. The client JSONDecodeError is a secondary parsing symptom, not a model
quality result. The chart query was withheld and no query was retried.

Previous deployment191 and exact original selected-agent context settings were
restored; the other144 stored overrides remained unchanged. Live UI access and
saved-result reopen were not established. HTTP content type/header request ID
were not retained; funding, organization verification and global model access
are unknown. This remains a failed controlled attempt, not a benchmark Pass.

Administrative remediation later on2026-10-21: explicit project-scoped access
authorization preserved all seven existing allowlist entries and added only the
two selected inference models plus the retained large embedding model. Admin
policy readback and the same runtime key's catalog confirm those additions. No
inference, deployment, key, billing, membership or rate-limit change occurred in
this step. The original failed runtime remains unchanged; working query/chart
delivery and UI acceptance are still unmet.


The one remaining controlled chart submission later ran on the unchanged
candidate after the access correction. It returned HTTP500 plaintext after
11.593s. Exact-request evidence shows the description selector chose orders and
order_status_history against the temporary orders-only policy; the pre-sampling
guard correctly rejected the excluded table with TableAccessPolicyError. Both
authorized submissions are spent, with no retry or successful query/chart. This
is a separate selection/policy consistency finding, not evidence that the
administrative correction failed or a model-quality benchmark result. Original
metadata restoration is independently verified; ROOT independently verified original191/image stability and the exact candidate
task STOPPED at21:45:51.239 IST before the effective deadline. Original flags,
classification and all144 overrides are restored. The list-index verifier
limitation is preserved; exact-known-task observations supplied stop proof. A
narrow selector/error-contract correction remains a proposal only.

## DA-010 — Selection uses the verified table catalog

2026-10-21 IST. Candidate only; no deployment or benchmark verdict change.
The controlled DA-009 chart request selected an excluded table through the
description branch. The pre-sampling guard refused it. The canonical selector
now verifies the existing identity-bound policy before work, filters descriptions
and fallback choices to that catalog, rejects excluded/unknown selections, and
keeps inherited denials terminal. Few-shot retrieval starts only after selection
is verified. SQL generation preserves that terminal state; its final fresh
pre-sampling check remains unchanged. Existing canonical final-answer/REST denial
is reused, yielding JSON with is_answered=false and no chart.

Ten focused offline methods passed0.499s using actual selector/node/REST function
bodies, synthetic external boundaries and blocked network sockets. Independent
review found the first candidate still did work on inherited denial; both
inherited-denial variants now have zero-work controls. Decorators/application
bootstrap/auth/storage/provider integration and primitive serialization are
omitted or doubled, so this is not live acceptance. No revised legacy174 overlay
or image is produced. Canonical source proof does not establish legacy release
behavior. The two original failed submissions, cleanup evidence and all17
published results remain unchanged. Required CI and independent candidate
acceptance are separate; further runtime remains outside the exhausted budget.

- [Selector](../../backend/agent/nodes/select_table_and_fewshots.py)
- [Terminal generation entry](../../backend/agent/nodes/sql_gen.py)
- [Focused actual selector and API bodies](../../tests/backend/test_selection_policy.py)

First CI39634677643 passed the new selector-policy job but failed the packaging
source-preservation check on two stale digests. Only those manifest entries were
updated for the changed source; original baselines/prior records and the first
CI failure are retained. This packaging correction changes no application code.

Independent source acceptance,2026-10-21 22:03IST: exacthead8d37fd0 passed
requiredCI39634921512, all four jobs. Canonical selector, terminal propagation
and existing non-streaming JSON denial contracts are accepted offline. Original
CI39634677643 failure and returned inherited-denial gap remain recorded. This
acceptance does not cover the unchanged legacy overlay, a release/merge/deploy,
real-model SQL/chart results, live UI, saved reopen or model accuracy. The two
failed live submissions and all17published results remain unchanged.


## DA-011 — One versioned model profile (2026-10-22 IST)

Candidate, not runtime accepted. Source inspection found competing defaults,
hidden provider substitution and destructive HC schema repair. The recommended
profile centralizes actual operations: Sol for complex reasoning, Luna for
lightweight work and small/1536 embeddings for new installations. Stored node
overrides and practical provider support remain. Existing vectors are never
silently dropped, resized or re-embedded; invalid configuration fails explicitly.

Eight new profile methods passed4.082s with actual SDK request serialization,
synthetic HTTP transport and real router/SQL/mapper schemas. Twelve selector
methods passed0.897s with config-error negatives; five adapter methods passed
3.621s. Initial test fixture removed Windows SystemRoot and failed SSL import;
fixture corrected, no live calls. These checks do not establish fresh-install,
UI/chart/restart/reopen/direct API or model-accuracy acceptance. Those gates and
clean-artifact verification remain pending. All previous failures and17 original
verdicts are unchanged. See [configuration](../model-configuration.md).


## DA-012 — Standard setup writes canonical table visibility (2026-10-22 IST)

Candidate, not runtime accepted. Independent inspection executed the complete
f7248/v4 direct table-description setup API: it returned success but persisted
integer1, which both strict policy readers rejected. This was a supported API
integration failure, not a live wizard failure. Current producers now emit
booleans. Explicit writes can normalize exact old0/1 without migrating other
records; description re-upload preserves existing exclusions. Malformed existing
configuration fails before a generation job can replace it with default allows.
Strict query readers, identity checks and SQL execution guards remain unchanged.

Four actual-body offline methods passed0.460s using synthetic ORM, source/model
and execution boundaries, with external sockets blocked. These cover writer to
strict readers, selector, sampling/execution boundaries and malformed/foreign
controls. A first job fixture omitted required globals and was corrected. No
live SQL/model/UI result is inferred from those tests.

First CI39730036046 stopped before Docker on an unchanged wizard validation
assertion. Other jobs passed; the isolated case and all415 local wizard/service
checks passed afterward. The CI cause remains unknown. Original source/export
and failures are retained. A corrected candidate CI and real UI/API journey are
still required; all17 original research verdicts remain unchanged.


## DA-013 — Business templates inherit model configuration (2026-10-22 IST)

The normal fresh-install wizard applied a default business template that saved a
Google SQL model, overriding an OpenAI-only installation. This was detected
before any ordinary question; no answer, SQL result or chart was accepted.
The temporary test stack was cleaned up. Existing benchmark verdicts are unchanged.

The candidate preserves template instructions while storing no model override.
The runtime inherits the current central profile, including rich file settings;
explicit developer node bindings retain their normal priority. Partial bindings
still fail. Configuration display resolves the current profile dynamically, and
the public model-edit API continues to require a complete model binding.
No schema migration, automatic record rewrite or prompt change is included.

Three focused actual-body tests passed0.342s with synthetic ORM boundaries and
outbound sockets blocked. These cover default creation/schema/template/persistence/
reader/settings, changed file and single-provider configuration, explicit stored
bindings, and malformed negatives. An initial settings fixture omitted agent
attributes and was corrected. Fresh UI/query/chart/restart/direct API acceptance
remains pending; offline passes are not a benchmark or runtime Pass.


Independent offline source acceptance: the reviewer matched the frozen candidate,
reran the three methods (PASS0.618s), and independently checked the actual prompt
reader and explicit datastore failure. Template instructions, nine protected
sources and all17 historical result tuples remain unchanged. Fresh runtime
acceptance is still pending; the first failed wizard evidence is preserved.


## One-key fresh-install qualification closeout (2026-10-22 IST)

Corrected application source `a349b68` passed required CI39736082550, all four
jobs. Independent review accepted a fresh complete installation with only the
OpenAI provider key: normal login/default wizard, canonical table permissions,
one UI query with exact SQL, complete typed rows and a rendered bar chart,
full five-service restart retaining three volumes, and saved GET-only reopen.
A second direct API request returned the correct rows with a file-only
final-answer model override, verified in the actual node and client metadata.
Exactly two ordinary questions were submitted; neither was retried.

The first fresh window's Gemini template override remains a recorded failure,
detected before any question. Its cleanup, initial CI failure, and earlier
metadata-writer witness are preserved. No historical benchmark result changes.
The corrected test resources were removed and the host verified stopped at
12:39:44 IST; production was unchanged. This is an isolated synthetic
installation proof, not a broad accuracy evaluation or production rollout.

The saved projection's top-level `is_answered` remained null despite live/stored
true, and a cosmetic header showed zero tables. Both are deferred; saved SQL,
complete rows and chart were intact. Exact HTTP attempt counts were unavailable;
model-constructor counts are not HTTP counts. Publication and license adoption
remain pending. [Qualification receipt](evidence/2026-10-22-one-key-qualification.json).


## Public source publication approved (22 October 2026 IST)

FutureSmart AI approved Apache-2.0 and a new fresh-history public repository for
this accepted reference application. This supersedes earlier pending-publication
and pending-license dispositions, which remain historical records of their
original phase. Private Git history and operator evidence are excluded; private
repository CI links are replaced by unlinked historical identifiers. No original
research verdict, application behavior, runtime result or deployment changed.
See the [publication notes](../publication.md) and root LICENSE/NOTICE.

## DA-014 — Hosted bring-your-own-key without silent platform fallback (2026-10-22 IST)

Released to the hosted service. On the hosted deployment several operations — table
selection, setup descriptions, chart post-processing and embeddings — built provider
clients without the owner's key and used the platform key, and a missing or unreadable
owner key fell back to it silently. Each owner now has an explicit key source: `own`
uses only the owner's stored keys and returns a clear, coded error otherwise; `platform`
keeps the previous behaviour, which standalone installations and existing hosted owners
retain. Browser sessions can now manage only their own credentials.

A legacy data shape surfaced during release review: every recently used hosted agent
stored table visibility as integers, which the strict access policy rejects. A one-time
migration stores exact 1/0 values as booleans; malformed or empty maps still fail closed.

Verified on the hosted service with the existing user, a new agent, a temporary
inference-scoped key and a read-only synthetic fixture: setup without a key failed
clearly; with the key, setup, SQL, two complete rows (South 200, North 250), a chart and a
saved-conversation reopen succeeded, attributed only to that key; after the key was
removed in the UI the next question failed with the missing-key message before any model
call or SQL. Temporary resources were removed. Hosted UI copy that still describes
platform fallback is a known follow-up. All historical verdicts are unchanged.

## DA-015 — First questions are not refused by a default business template; an identifier is not a chart series (2026-10-23 IST)

Released to the hosted service. The 2026-10-22 landing-page audit found two first-impression
defects on a synthetic shop database.

A new agent's first "top five customers by total spend" question was sometimes refused, and
its follow-up was refused too. Every agent created without a `template_id`, including every
agent created from the hosted UI, received the SaaS founder template, whose rules say a
customer counts only with a live, paid subscription and a successful payment. A shop database
has neither. On the production prompt and model, 40 fresh first questions per arm, the template
refused 6 of 40 and no template 0 of 40; every refusal reason cited those rules. New agents now
get no template unless the creator chooses one. A refused turn keeps its question in the
conversation history but no longer its refusal text, which had led the next turn to refuse
again. The model's refusal reason is now logged.

A bar chart of the same five customers became a stacked chart split by surname. The chart check
counted the selected customer `id` as a second measure. The mapping model now names the plotted
measures and the label columns, the check counts only those measures, and a first and last name
become one label.

Source connections now always use the stored port. Table listing, column listing, the documented
table-description upload and the column profiler had connected to the engine's default port, so a
PostgreSQL database on 5434 failed them.

Verified on the hosted service with a new agent created without a template on a read-only
synthetic fixture: no business instruction stored for the agent; 15 of 15 fresh first questions
answered with the exact five rows; an unsupported subscription-revenue question was refused, the
reason logged, and the next supported question in the same conversation answered. The chart
behaviour was verified with the real models on the merged code (a bar chart with full-name labels,
and a two-measure control that still stacks). Existing agents that already store the template
are unchanged. All historical verdicts are unchanged.

## DA-016 — Try Database Agent on sample data, without a key or a database (2026-10-23 IST)

Released to the hosted service. A signed-in user now sees "Try with sample data" on the home
screen and can ask a shared agent about Cedar Lane, a synthetic online shop with a year of
customers, orders, payments and returns, without adding an OpenAI key or connecting a database.

Each person gets 5 free questions per rolling 24 hours and 20 in total, and all free questions
together stop at a monthly spending budget. A question is counted before it runs, so questions
sent at the same time cannot exceed the allowance: on the hosted service four questions sent at
once with three left ran three and refused the fourth. When the free questions are used up, the
screen says why and links to adding your own key, connecting your own database, or running
Database Agent yourself. Anyone other than its owner can only ask the sample agent questions;
attempts to change its settings, database, keys or collaborators, or to read other users'
questions, are refused.

The database and its answers are reproducible: a seeded generator builds it, and each suggested
question has a reference answer computed twice, in Python and in SQL. On the hosted service the
suggested questions returned the reference rows, the bar chart of the top five customers showed
one bar per customer with full names, and a follow-up narrowed it to the top two.

Two problems found during verification were fixed or recorded. Descriptions written while the
automatic description job was still running were overwritten by it, which made the agent pick
its own definitions of revenue and return rate; the sample agent's definitions are now written
after the job and checked. The hosted service has not recorded per-question cost since
2026-10-02, so spend is estimated from recorded tokens at the product's blended rate (about
$0.028 per sample-data question).

## DA-017 — Sample data ready for researcher feedback (2026-10-23 IST)

Released to the hosted service. Each person now gets 20 free sample-data questions per rolling
24 hours and 100 in total. People signed in with a verified aidemos.com or futuresmart.ai email
have no limit, so the team can test without resets; their questions are still recorded, but kept
apart from public usage and out of the $150 monthly budget, so both costs can be read separately.

Every answer has "Report a problem": say what went wrong and what you expected, and the service
attaches the conversation up to that answer (each question, the SQL, the rows and the chart). The
person gets a report id to quote.

Fixed along the way, each checked on the hosted service:

- Descriptions written right after adding a database were overwritten by the automatic
  description job; they are now kept (reproduced on the old release, gone on the new one).
- The header said "0 tables" for every agent; it now counts the tables the agent may read.
- Picking a suggested question puts the cursor in the box, so Enter sends it.
- Answers now read the business definitions, so amounts come out in dollars instead of
  "the result does not specify a currency"; 8 of 8 reference questions matched.
- A follow-up like "Only show the top two." after a chart now keeps the chart (3 of 3 runs,
  previously 0 of 3).
- On the shared sample agent, a visitor's thumbs-down no longer rewrites the stored SQL of their
  answer.
- The API was killed for running out of memory at 512 MB under a description job and questions
  together; it now has 1 GB.

Still open: questions take 13 to 50 seconds, and the shared database cluster is at its 1 ACU
ceiling every hour (a capacity decision is pending).

## DA-018 — Saved conversations stay on their agent and under its answer settings (2026-10-23 IST)

Released to the hosted service. Each agent now only ever sees its own turns of a conversation.
Before, chat history was read by conversation id alone: someone allowed to use one agent could
pass another agent's conversation id and have that agent's questions and answers replayed into
this agent's model context. A conversation created on another agent is now refused before the
question is charged, any history is read or a model is called. An id the API never created —
the FutureSmart chat service sends its own thread id to every agent it calls — keeps working,
with only this agent's turns as context.

Hiding the SQL or the result rows in Settings now also hides them when a saved conversation is
reopened through the API, not only in the live answer, and the CSV download is refused for an
agent that hides rows. An agent key can no longer download another agent's results or change
the feedback on another agent's answers.

Verified on the hosted service with two temporary agents on the synthetic Cedar Lane data, one
showing SQL and rows and one hiding them: 30 of 30 checks, including the refusal in under a
second with nothing written to the other conversation, a shared chat-service thread where the
second agent read none of the first agent's turns, replays and downloads following each agent's
settings, the MCP server journey, and the free sample-data agent answering and reopening as
before. The same change is in the public repository.

Found during verification: setting up two agents at once while a question ran exhausted the
API's 1 GB of memory and the service restarted (about three minutes of errors); recorded as
DA-MEM-002. The hosted master key had been committed to the chat service repository; it was
rotated the same evening (DA-SEC-001).

## DA-019 — The public API lives at futuresmart.ai/database-agent/api (2026-10-24 IST)

The hosted API's canonical public root is now https://futuresmart.ai/database-agent/api,
under the FutureSmart AI site rather than an application subdomain. It is the same
service: the futuresmart.ai web server forwards the path to the existing /nl2sql/api
routes, which keep working unchanged at https://app.futuresmart.ai/nl2sql/api. The API
reference at /docs works at both roots and its "Try it out" calls the public root. The
Share page's API examples, the landing page samples and the public repository's API and
MCP documentation name the new root, and the landing page's integration section now
includes the MCP server. The hosted application pages are marked noindex so they do not
compete with the product landing page.

Verified on the hosted service with temporary synthetic agents through the new root: the
production journey (answers, follow-ups, session isolation, replay settings, CSV export,
key scope, MCP tools), streamed answers arriving unbuffered, exact forwarding of encoded
paths, and the same conversation replayed through the old root.

## DA-020 — Model evaluation through the real API, and per-answer latency and cost (2026-10-25 IST)

A repeatable model evaluation now lives in `tests/evaluation/model_eval`. It asks 18 questions
over two synthetic databases — the Cedar Lane sample database with its reference answers, and
a new, structurally different clinic schema — through the product's own chat API with the
real model pipeline, and grades every answer against ground truth computed twice (Python over
the generated rows, and reference SQL on the loaded database). A judge model compares the
returned rows and prose with that ground truth; a mechanical row comparison, SQL validity on
the read-only role, latency, estimated cost and the models actually used are recorded beside
it. Each run is a LangSmith experiment over a versioned dataset. The **Model evaluation**
workflow runs it weekly and on demand on the existing Compose stack.

Every chat answer now carries `usage`: the agent's processing time, tokens, and a list-price
cost estimate per pipeline step from a dated price table. Totals come from a run-level count
of every model call, so a call no step records itself still appears (`other_calls`); an
unpriced model makes the cost incomplete instead of free. The same per-step estimates are
stored with each Agent Health event, and the conversation's Full logs panel shows them.

First experiment (two runs, four answers per question and configuration): the shipped
configuration answered 70 of 72 correctly; moving table selection, database routing, SQL
generation and pandas planning from gpt-6.1-sol to gpt-6-luna answered 65 of 72, at about
one seventh of the estimated cost ($0.0007 vs $0.0047 per answer) and about a second faster
at the median. The cheaper configuration failed where two grains must be aggregated before
they are joined (clinician utilisation, 0 of 4) and where "seen" had to be read as
"attended" (1 of 4). The shipped model failed once in two by adding `LIMIT 10` to a
twelve-month question; it ended 17 of 36 queries with that limit against the prompt's rule
(DA-LIMIT-001). The evaluation also showed that table selection — 35% of the shipped
configuration's cost — had been missing from cost reporting; it is now counted.
No production model was changed. Evidence: `docs/improvements/evidence/2026-10-25-model-evaluation.json`.

## DA-021 — One development repository for Database Agent (2026-10-25 IST)

Database Agent is now developed in one repository only. The hosted application's interface
had been built from a separate UI repository, and the public repository had received changes
of its own (the MCP server among them), so the same product was being edited in three places.
Everything that existed only in those two copies was brought into the development repository:
the sample-data entry and free-question allowance, Report a problem and the canonical API root
from the UI repository, and the MCP server, the saved-replay `result` block it reads, the
license files and public documentation from the public repository.

The hosted interface now deploys from the development repository on every merge that changes
it, and the separate UI repository is archived with its history kept. The public repository is
now a release snapshot: `deploy/publish_public.py` exports one development commit, refuses to
publish if the public repository was edited directly, and records the exact files and the
source commit in `docs/source-export.json`. The first release under this process reproduced
every public change and added the work since its first publication (DA-014 to DA-020).

Verified on the hosted service through the public API root on the free sample-data agent: an
answer with its usage block, a follow-up, a streamed answer, a saved conversation returning
column-labelled rows, a problem report with its conversation snapshot, and the MCP server over
the hosted API. The hosted interface serves the new release with every feature above. The
public release passed its own complete check suite. Evidence:
`docs/improvements/evidence/2026-10-25-single-development-repository.json`.

## DA-022 — Full logs shows every operation; last outside copy of the UI removed (2026-10-26 IST)

A signed-in walkthrough of the hosted interface after DA-021 (sample data, an answer, follow-ups,
a reopened conversation, Report a problem, Share → API) found one defect: Full logs listed three
of the seven operations an answer paid for, named the model on one step only, and showed no usage
on a reopened conversation. The interface read only the steps it knew by name, and the usage block
was returned with the answer but not stored with it. The usage block is now stored with each turn
and returned on saved replay, and Full logs lists every operation with its model, time, tokens and
estimated cost under a total that matches the answer.

The release build's base image also moved twice. Docker Hub refused CodeBuild's anonymous pulls,
and the first fix (AWS's public mirror) was wrong to claim the mirror had no anonymous limit: it
throttled GitHub's runners. The Dockerfile now takes the base image as a build argument; the
release build, defined in `deploy/codebuild/api-buildspec.yml`, logs in to the mirror and passes
it, while every other build pulls Docker's official image.

The copy of this interface that remained in `futuresmart-agent-ui` (`apps/nl2sql` and the routes
wrapping it) was removed there (PR 255); nothing served it and nothing in it was unported.

This closed the development cycle: the weekly model evaluation now runs only on demand, and
[product capabilities](../product-capabilities.md) summarises what exists today, hosted and
standalone, with links to each guide.

Verified on production: Full logs on a live answer and on a reopened conversation (seven
operations each), API task definition 218 built through the repository buildspec, and the shell
and product pages after the removal. Evidence:
`docs/improvements/evidence/2026-10-26-full-logs-and-cleanup.json`.
