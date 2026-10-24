# Direct product API

Local API root: `http://127.0.0.1:18000/nl2sql/api`.
Hosted API root: `https://futuresmart.ai/database-agent/api`, with the same routes
below and an interactive reference at
[/database-agent/api/docs](https://futuresmart.ai/database-agent/api/docs). The
hosted `https://app.futuresmart.ai/nl2sql/api` root keeps working.
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

An agent only ever sees its own turns of a conversation: chat history and replays
are read for that agent alone. A `session_id` this API created for another agent
returns HTTP404 before any history is read or a model is called; a `session_id`
the API did not create (for example a chat service's own thread id) continues
with this agent's turns only.

`show_sql_query` and `show_db_result` apply to saved conversations exactly as to
live answers: a replay leaves out the SQL and the rows (`debug_info.db_output`
and `result`) the agent hides, and `GET /v1/sessions/{session_id}/export` returns
HTTP403 for an agent that hides result rows; with an agent key it finds only that
agent's turns. Both settings are read when the
conversation is served, so turning one back on shows the stored SQL or rows again.

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
