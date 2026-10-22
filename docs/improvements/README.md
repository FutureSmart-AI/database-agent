# Database Agent: research-driven improvement history

Recorded on 21 October 2026 (IST). This is a public-facing history of our own
reference application. It preserves failures, decisions and limited validation
alongside successful fixes. It is not a leaderboard or a current accuracy score.

- [S64 retrospective: unsupported data was reported as zero](S64-unsupported-data.md) — original Fail unchanged; correction released; independent benchmark retest pending.
- [Original evaluation baseline and published sources](baseline.md)
- [Dated 17-result documented baseline and unchanged verdicts](published-results.md)
- [Engineering history, including unfinished and declined work](history.md)
- [Structured public records](records.json)
- [How maintainers must update the history](MAINTAINING.md)

Published research verdicts stay as published. Private case-level verdicts are
preserved separately and are not disclosed without publication approval. A fix,
new passing fixture, green CI job or deployment does not rewrite a benchmark.
Implementation identifiers below are recorded provenance; future fresh-history
source distributions may not include the original private commits. Current
source/test links remain the practical way to inspect the released behavior.

Current release qualification (22 October 2026 IST) covers the centralized model
profile, one-key installation, ordinary UI/API journey and a clean source export.
The documented 17-result baseline is sufficient; additional research belongs to
later public iterations. PR77/PR79 are deferred unless an ordinary-flow failure
requires them. Earlier issue queues in dated records are historical context.
This history does not independently authorize model calls or deployment. Candidates
are explicitly labelled and are not features of the current accepted release.

S60/DA-008 has scoped independent source/synthetic acceptance on562db70 with
all required CI checks passed (historical private identifier 39605744198; original link omitted).
This is accepted source for integration, not a production deployment or an upgrade
to the original published Fail. See the detailed history for preserved initial
candidate and CI failures, accepted controls and remaining limits.


The 22 October 2026 [one-key qualification receipt](evidence/2026-10-22-one-key-qualification.json)
records the accepted fresh UI/API installation, preserved first-run failure,
restart/reopen evidence and remaining release limits. It does not replace or
upgrade any published benchmark verdict.


Apache-2.0 and the new public source repository were approved after qualification;
see [publication notes](../publication.md). Earlier pending-release wording in
dated records describes its original phase and is not a benchmark verdict.
