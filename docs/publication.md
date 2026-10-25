# Public source release and retained compatibility URLs

22 October 2026 IST. FutureSmart AI approved a new public repository,
[FutureSmart-AI/database-agent](https://github.com/FutureSmart-AI/database-agent),
under [Apache-2.0](../LICENSE). Copyright 2026 FutureSmart AI; see [NOTICE](../NOTICE).
This source starts with fresh Git history from the accepted reference application.
Private repositories, history and operator evidence are not part of the release.

## Verification and evidence boundaries

The [qualification receipt](improvements/evidence/2026-10-22-one-key-qualification.json)
records two questions on a four-row read-only synthetic fixture: normal UI setup,
SQL/full typed rows/chart, full stack restart/saved reopen, and a direct API
answer-presentation model override. This is installation and connectivity proof,
not a current general accuracy score, load test or benchmark verdict upgrade.
All 17 published results retain their original verdicts. Historical commit/PR/CI
identifiers in the improvement history are provenance only; their original
private links are omitted rather than redirected to unrelated public commits.

## Retained URL categories

These are source compatibility constants or public resource references, not
credentials or unpublished deployment addresses. Their presence does not mean
that each path is required, enabled or validated by the standalone installation.

| URL category | Source boundary and disposition |
|---|---|
| `futuresmart.ai`, `aidemos.com` | Public company branding and published research/result links. Retained. |
| `auth.futuresmart.ai` | Hosted authentication compatibility in backend auth helpers and frontend configuration. The supported Compose path sets standalone mode; local login uses `/nl2sql/api/v1/local-auth` and requires no FutureSmart account. See `backend/standalone/auth.py`, `frontend/src/platform/config/index.ts`, and `compose.yaml`. |
| `agent.futuresmart.ai` | Retained hosted authorization/public-host defaults. Centralized authorization compatibility helpers remain in source; this release's single-operator flow uses local product authentication. These URLs are not a new shared-service deployment requirement. |
| `app.futuresmart.ai` | Existing development rewrite fallback, contract-generation tooling and compatibility examples. Static Compose serving uses `frontend/nginx.conf` to proxy the product API to its local `api` service. Configure local API origins for development as described in the frontend guides. |
| `stt.futuresmart.ai` | Optional hosted voice gateway compatibility. Voice UI is disabled without an explicitly supplied public gateway configuration; no private key is bundled. Voice was not part of the two-question qualification. |
| `futuresmart-rag-bot.s3.us-east-1.amazonaws.com` | Public company branding/logo URL and test fixtures. A public asset reference is not a datastore credential or a grant to private objects. |
| Provider API domains | Supported provider validation/client endpoints. The recommended profile requires only the operator's OpenAI key; no provider key is in source or the browser. |
| Google Drive/Docs URL patterns | Generic document-ID/link parsing in compatibility utilities. No private document ID is supplied by the release. |
| Localhost, Compose service names, example/test domains | Local installation, proxies and synthetic test fixtures. Retained. |
| Font/upstream documentation and public media hosts | Original font license/source references and existing public media handling. Bundled font bytes and their OFL notices are unchanged. |

## Distribution

This repository is a release snapshot of FutureSmart AI's development repository, where
the product — backend, frontend, MCP server, tests, evaluations and model configuration — is
developed, reviewed and deployed. Each commit on `main` here is one release, produced by
`deploy/publish_public.py`:

1. `deploy/export_source.py` archives one development commit, leaving out private
   records, Git history and the hosted deployment, evaluation and publication workflows. It
   refuses a snapshot that contains an environment file, a hosted workflow or a link to a
   private repository.
2. Before writing, the publisher checks that this repository still matches the manifest of
   its last release. A file changed here directly stops the release until that change has
   been brought into the development repository, so nothing is overwritten and nothing is
   developed in two places.
3. It replaces the files, writes `docs/source-export.json` (exact file hashes, the source
   commit and the license; the manifest omits its own hash) and commits.

A release is pushed to `main` by a FutureSmart maintainer; a repository ruleset lets no one
else update `main`. Contributions are welcome as
issues and pull requests (see `.github/CONTRIBUTING.md`); accepted changes reach `main`
through the next release. Original font copyrights and OFL license notices remain separate
from Apache-2.0.
