# Current published scenario Results

Checked21 October2026 IST. These17 pages are distinct from the older23 criterion
observations and August feature labels retained in baseline.md. Original Pass/Fail
is preserved. Connected-data answering has four test cases; the other16 have one.
Different test sets are not combined into a product accuracy score. Historical
hosted build/version is not exposed; no exact current benchmark rerun is claimed.

| Published Result | Original verdict | Cases | Observed behavior | Current engineering relationship |
| --- | --- | --- | --- | --- |
| [find reported bad answer](https://aidemos.com/benchmarks/ai-database-agents/results/futuresmart-ai-database-agent/find-reported-bad-answer) | Pass | 1 | Target exchange found in logs and Activity; five-query scale only. | Historical control; exact current replay not established. |
| [failed question surfacing](https://aidemos.com/benchmarks/ai-database-agents/results/futuresmart-ai-database-agent/failed-question-surfacing) | Fail | 1 | Failures view empty while unsupported questions were marked answered. | DA-001 handles explicit unsupported outcomes; end-to-end analytics classification remains unverified. PR79 saved flags are a separate candidate. |
| [plain fact or short list](https://aidemos.com/benchmarks/ai-database-agents/results/futuresmart-ai-database-agent/plain-fact-or-short-list) | Pass | 1 | Plain prose and a count grid agreed on100 orders. | Historical presentation control, not a current database recount. |
| [the answer needs a summary and its detail together](https://aidemos.com/benchmarks/ai-database-agents/results/futuresmart-ai-database-agent/the-answer-needs-a-summary-and-its-detail-together) | Pass | 1 | Overall revenue paired with seven-category table and chart. | DA-002 renderer fix released separately; no historical scenario upgrade. |
| [same answer different format](https://aidemos.com/benchmarks/ai-database-agents/results/futuresmart-ai-database-agent/same-answer-different-format) | Fail | 1 | Chart-only follow-up changed values and refund filtering and denied chart rendering. | DA-002 fixes a separate renderer defect; DA-003/PR77 semantic continuity remains unaccepted. |
| [customer corrects information given earlier](https://aidemos.com/benchmarks/ai-database-agents/results/futuresmart-ai-database-agent/customer-corrects-information-given-earlier) | Pass | 1 | June correction replaced July without carrying forward the earlier period. | Historical corrected-period control; no new implementation. |
| [the follow up is ambiguous](https://aidemos.com/benchmarks/ai-database-agents/results/futuresmart-ai-database-agent/the-follow-up-is-ambiguous) | Fail | 1 | Ambiguous comparison follow-up was interpreted without clarification. | No accepted exact ambiguity fix or current replay. |
| [the user changes direction mid conversation](https://aidemos.com/benchmarks/ai-database-agents/results/futuresmart-ai-database-agent/the-user-changes-direction-mid-conversation) | Fail | 1 | Overall cancellation request became state-level refund rates. | Existing DA-003/PR77 metric and scope work remains unaccepted. |
| [the user narrows what they just asked](https://aidemos.com/benchmarks/ai-database-agents/results/futuresmart-ai-database-agent/the-user-narrows-what-they-just-asked) | Pass | 1 | Narrowing retained the original date window and added Texas. | Preserve historical control and separate ordering/pagination caveats. |
| [an excluded table is needed to answer the question](https://aidemos.com/benchmarks/ai-database-agents/results/futuresmart-ai-database-agent/an-excluded-table-is-needed-to-answer-the-question) | Fail | 1 | Refusal accompanied excluded returns SQL/read and a zero result. | DA-008: scoped fail-closed/CTE source independently accepted at562db70 after full CI39605744198; not deployed and original Fail unchanged. |
| [the answer is available in the connected data](https://aidemos.com/benchmarks/ai-database-agents/results/futuresmart-ai-database-agent/the-answer-is-available-in-the-connected-data) | Pass | 4 | Four connected-data questions returned the recorded reference answers. | Different test set; evaluator reliability does not establish a fresh model benchmark Pass. |
| [the connected data cannot answer the question](https://aidemos.com/benchmarks/ai-database-agents/results/futuresmart-ai-database-agent/the-connected-data-cannot-answer-the-question) | Fail | 1 | Unsupported review count was replaced with a zero from an unrelated activity log. | DA-001 released with separate staging/production controls; original benchmark Fail remains. |
| [business defined term](https://aidemos.com/benchmarks/ai-database-agents/results/futuresmart-ai-database-agent/business-defined-term) | Pass | 1 | Answer stated its revenue definition and SQL matched that interpretation. | Historical definition-disclosure control; cross-turn preservation remains separate. |
| [the users wording doesnt match how the values are stored](https://aidemos.com/benchmarks/ai-database-agents/results/futuresmart-ai-database-agent/the-users-wording-doesnt-match-how-the-values-are-stored) | Fail | 1 | Voucher wording missed stored matching payment values and returned empty. | Value grounding remains unresolved; no benchmark-specific synonym mapping. |
| [relative date report](https://aidemos.com/benchmarks/ai-database-agents/results/futuresmart-ai-database-agent/relative-date-report) | Fail | 1 | Initial relative-window count shown, but saving/data-change/rerun comparison was not demonstrated. | Existing report source does not prove historical rerun; evidence/method limits preserved. |
| [definition correction](https://aidemos.com/benchmarks/ai-database-agents/results/futuresmart-ai-database-agent/definition-correction) | Pass | 1 | Repeated and paraphrased questions retained the corrected cancellation exclusion. | Historical in-conversation rule control, not cross-session training proof. |
| [standing rule persistence](https://aidemos.com/benchmarks/ai-database-agents/results/futuresmart-ai-database-agent/standing-rule-persistence) | Pass | 1 | Two later answers retained one standing exclusion rule. | Historical limited-turn control; no broad persistent-learning claim. |

The S60 engineering sequence is recorded in [DA-008](history.md#da-008).
The original unsupported-data failure is linked to the existing released
[DA-001](history.md#da-001), without changing its original Fail.
Published outcomes, source findings, synthetic reproduction, implementation,
independent acceptance and deployment are separate claims. Private research
discussions and unpublished case material remain excluded.
