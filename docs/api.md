# Direct product API

Local API root: `http://127.0.0.1:18000/nl2sql/api`.
Interactive reference: [/nl2sql/api/docs](http://127.0.0.1:18000/nl2sql/api/docs).
Machine contract: [/nl2sql/api/openapi.json](http://127.0.0.1:18000/nl2sql/api/openapi.json).
The UI calls the same product API through its same-origin proxy. MCP clients
such as Claude Code can call it through the [MCP server](mcp.md).

Trusted operator clients use the private `FASTAPI_SECRET_KEY` as `X-API-Key`.
The agent-key endpoint issues a narrower agent credential for chat. Keep both
types private and pass them in memory through an HTTP client, outside source,
command arguments, browser storage, and logs. Browser standalone login instead
uses the signed HTTP-only session cookie; no hosted Auth service is required.

| Route, relative to the API root | Existing flow |
|---|---|
| `GET /health` | Reachability; does not prove inference success |
| `POST /v1/agents` | Create an agent for the configured operator/owner |
| `POST /v1/agents/{id}/databases` | Attach the read-only PostgreSQL/MySQL source |
| `POST /v1/agents/{id}/databases/{db_id}/tables` | Supply table descriptions/visibility |
| `POST /v1/agents/{id}/api-keys` | Issue an agent key; never log the returned key |
| `POST /v1/agents/{id}/chat?stream=false` | Direct question with JSON response |
| `POST /v1/agents/{id}/sessions/{session_id}/messages?stream=false` | Follow-up in a conversation; the session must belong to this agent |
| `GET /v1/agents/{id}/sessions` | Saved conversations on the agent |
| `GET /v1/agents/{id}/sessions/{session_id}` | A saved conversation, each answer with its SQL, `result` rows and chart |

Use the generated OpenAPI contract for complete request/response fields and
streaming options. `tests/evaluation/run.py` is a small working client example:
it loads configuration privately, creates the sample agent/source/table, issues
an agent key in memory, asks a question, and independently verifies the SQL and
returned answer. It prints only safe test outcomes. Run it through the Compose
evaluation command in the root README.

Results may contain SQL, rows, answer/status, follow-ups, and optional chart
payloads according to agent settings. Preserve numeric rows/units when consuming
them. Released chart behavior and evidence are described in the improvement
history; a successful SQL execution alone does not establish a rendered chart or an
answerable question. Ordinary asynchronous setup/chat work belongs to this API;
there is no required shared orchestrator or separate core worker process.

Invalid model configuration returns HTTP400 with `detail.code` equal to
`model_configuration_error` and a nonsecret operator message. Streaming failures
use the existing error metadata event; they do not substitute a different model.
