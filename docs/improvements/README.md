# Research findings and engineering outcomes

This is the navigation hub for how AI Demos research and maintainer investigation
shape FutureSmart Database Agent. Start with a finding, inspect the engineering
record, then check what was actually verified. The index is not a leaderboard or
a claim that every reported problem has been fixed.

## Benchmark findings

| Scenario and original evidence | What research found | Engineering outcome | Details and verification limits |
|---|---|---|---|
| [S64 — original Fail](https://aidemos.com/benchmarks/ai-database-agents/results/futuresmart-ai-database-agent/the-connected-data-cannot-answer-the-question) | Unsupported review information was reported as zero using an unrelated activity log. | **Correction released; benchmark retest pending.** | [Complete case study](S64-unsupported-data.md): answerability code, mocked regressions and recorded separate historical browser checks. [Public PR #1](https://github.com/FutureSmart-AI/database-agent/pull/1) is retrospective documentation, not the historical fix PR. |
| [S60 — original Fail](https://aidemos.com/benchmarks/ai-database-agents/results/futuresmart-ai-database-agent/an-excluded-table-is-needed-to-answer-the-question) | The agent refused an answer but still read an excluded table and returned a result. | **Scoped source fix accepted; production deployment not claimed.** | [DA-008 engineering record](history.md#da-008-verify-table-access-before-reading-source-data): fail-closed access controls and synthetic/independent source validation. No accepted benchmark retest. |
| [S43 — original Fail](https://aidemos.com/benchmarks/ai-database-agents/results/futuresmart-ai-database-agent/the-user-changes-direction-mid-conversation) | A request for one overall cancellation rate became a by-state result using refund events. | **Investigation/candidate; semantic correction not independently accepted for release.** | [DA-003 engineering record](history.md#da-003-preserve-metric-meaning-when-changing-scope). Candidate work is separate from the accepted application; no new implementation or benchmark retest is claimed here. |
| [S53 — original Fail](https://aidemos.com/benchmarks/ai-database-agents/results/futuresmart-ai-database-agent/same-answer-different-format) | A chart-only follow-up lost a refund filter, changed values and denied chart rendering. | **Semantic correction not accepted.** | [Related DA-003 metric/scope work](history.md#da-003-preserve-metric-meaning-when-changing-scope). The separate [released DA-002 renderer fix](history.md#da-002-render-nested-stacked-chart-results-without-losing-series) does not establish a fix or benchmark Pass for S53. |

These original results remain **Fail**. Engineering release, source acceptance,
production deployment and an independently accepted benchmark retest are different
states. No independently accepted retest is recorded for the four findings above.
The [dated 17-result baseline](published-results.md) covers the other published
scenarios too, including original Pass results; it is not a new accuracy score.

## Other engineering records

Some work responds to an installation or maintainer finding rather than a single
published benchmark case. Follow the linked record for its original failures,
code/test references, independent checks and remaining limits.

| Record | Engineering response | Current evidence boundary |
|---|---|---|
| [DA-002 — chart rendering](history.md#da-002-render-nested-stacked-chart-results-without-losing-series) | Released normalization of nested and flat chart results. | Separate renderer defect and live/saved display checks; not acceptance of S53 metric/filter continuity. |
| [DA-004 — answer delivery and persistence](history.md#da-004-deliver-and-save-the-primary-answer-before-optional-work) | Candidate delivery and saved-result work. | Independent acceptance remains incomplete; no production promotion claimed. |
| [DA-005 — installable reference application](history.md#da-005-preserve-a-complete-installable-reference-application) | Source accepted for one-repository installation. | Installation evidence does not establish general answer quality or load capacity. |
| [DA-006 — speed and correctness](history.md#da-006-evaluate-speed-together-with-correctness) | Evaluation-only investigation. | No accepted quality winner or general performance claim. |
| [DA-007 — evaluator reliability](history.md#da-007-reject-false-positive-evaluation-results) | Independently accepted evaluator source controls. | Synthetic comparator/fixture verification, not product or model accuracy. |
| [DA-009 — earlier one-provider attempt](history.md#da-009--one-provider-for-default-model-operations) and [DA-010 — selection policy](history.md#da-010--selection-uses-the-verified-table-catalog) | Failed provider/selection attempts retained; later selector source accepted. | Preserve the failures and source-review limits. Later successful installation evidence is recorded separately below. |
| [DA-011–DA-013 — model profiles and setup](history.md#one-key-fresh-install-qualification-closeout-2026-10-22-ist) | Central model configuration, canonical table flags and template inheritance. | [Bounded one-key installation qualified](evidence/2026-10-22-one-key-qualification.json): two questions on four synthetic rows, UI/chart, restart/saved reopen and direct API override. Not a benchmark retest. |
| [DA-DEC-001 — product scope](history.md#da-dec-001-core-capability-quality-takes-precedence-over-commercial-feature-parity) | Core quality takes priority over speculative feature parity. | Deferred capabilities remain explicit; this is a scope decision, not an implemented feature. |

## Explore the evidence

- [Detailed engineering history](history.md) — decisions, implementation, validation and limits.
- [Structured engineering records](records.json) — the current public status source for this index.
- [Published results and original verdicts](published-results.md), [machine-readable results](published-results.json), and [source baseline](baseline.md).
- [Maintainer summaries](evidence/2026-10-22-one-key-qualification.json) and [S64's historical validation boundaries](S64-unsupported-data.md#regression-controls-and-recorded-independent-validation).
- [History-maintenance rules](MAINTAINING.md) and [publication/source boundaries](../publication.md).

## How future improvements are tracked

New work should connect a **public issue → implementation PR → independent product
acceptance → history/index update → appropriate separate research retest**. Each
step records its actual outcome; a green CI job does not upgrade a benchmark.
A retest, when appropriate and authorized, produces new evidence while retaining
the original result. This index does not schedule or authorize any new run.

Existing corrections can predate the public repository. Their retrospective
records identify the actual public code and already approved validation without
inventing historical public issues or PRs. Create a detailed case study when
meaningful engineering work warrants one; keep the main README to one useful
example and this index as the place to explore the rest.
