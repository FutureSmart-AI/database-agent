# Configuration

Run `python deploy/configure.py` with Python 3.11, or use the Docker command in
the root README. It creates `.env` from `.env.example` with independent login,
API-signing, and credential-encryption secrets. It never overwrites an existing
configuration or prints secret values.

Process environment takes precedence. `ENV_FILE` selects an explicit backend
file; otherwise the backend reads `backend/.env`, then root `.env` if present.
Historical environment variants are not discovered automatically. Compose
mounts the generated root file at `/app/.env`.

| Setting | Purpose |
|---|---|
| `MODE=standalone` | Local login and independent product operation |
| `FASTAPI_SECRET_KEY` | Private master API credential and session signing |
| `STANDALONE_LOGIN_PASSWORD` | Single-operator UI password |
| `STANDALONE_OWNER_EMAIL` | Operator identity; default `operator@example.test` |
| `STANDALONE_ORIGIN` | Exact browser origin, including port; no path |
| `STANDALONE_COOKIE_SECURE` | False for local HTTP; true for hosted HTTPS |
| `APP_MASTER_KEY`, `HASH_SALT` | Durable encryption material; retain with backups |
| `OPENAI_API_KEY` | Required by the recommended default profile; other provider keys only for explicit overrides |
| `POSTGRES_*` | Product metadata connection, separate from the queried source |
| `DATABASE_URL` | Optional metadata override for runtime and Alembic |
| `qdrant_url`, `qdrant_api_key` | Vector database connection |
| `REPORTS_EXECUTOR=inprocess` | Existing optional report executor in the API |
| `REPORTS_SCHEDULER_ENABLED=false` | Disable scheduled reports locally |

Compose supplies the same isolated metadata address to every backend service.
To replace that database, update those Compose entries together. Source
credentials are entered separately in the wizard. `sample-db` is a container
hostname, not a browser URL.

Tracing, the central usage mirror, and S3 exports are disabled locally. Ordinary
setup/chat needs no hosted Auth, Chat, Dashboard, Usage, Memory, or external
report worker. Hosted SSO remains available through explicit hosted settings.

Inject provider keys through the shell locally and Secrets Manager references
on ECS. Never put them in public frontend settings, source, image builds,
browser storage, or screenshots. Existing provider settings encrypt stored
credentials with the durable keys; broader hosted multi-user isolation is
outside this installation scope.

Model assignments and advanced overrides use the [single versioned resolver](model-configuration.md).
