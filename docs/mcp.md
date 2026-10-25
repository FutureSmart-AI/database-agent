# MCP server

> Connecting to the hosted product? Follow
> [MCP server and Claude Code](https://futuresmart.ai/docs/database-agent/mcp) in the
> developer docs. This page covers the same server against a local installation.

`mcp-server/` lets MCP-compatible AI applications, such as Claude Code, use your
Database Agent agents as tools. It is a thin adapter over the
[direct product API](api.md): every tool call is an ordinary API request made
with an existing Database Agent credential. Authentication, agent-key scope,
query limits, model configuration, table visibility, SQL access controls and
query execution all stay in the API. The adapter has no database credentials and
does not generate or run SQL.

## Tools

| Tool | What it does | API route |
|---|---|---|
| `list_agents` | Agents these credentials can use, with connected databases (name, engine, description, table count; never host, user or password) | `GET /v1/agents`, `GET /v1/agents/{id}`, `GET /v1/agents/{id}/databases` |
| `ask_database` | Ask a question; returns the answer, generated SQL, column-labelled rows, chart suggestion and metadata, and a `session_id` | `POST /v1/agents/{id}/chat?stream=false` |
| `ask_database` with `session_id` | Follow-up question using that conversation's context | `POST /v1/agents/{id}/sessions/{session_id}/messages` |
| `list_conversations` | Saved conversations on an agent, newest first | `GET /v1/agents/{id}/sessions` |
| `get_conversation` | A saved conversation: each turn's question, answer, SQL, rows and chart | `GET /v1/agents/{id}/sessions/{session_id}` |

Every tool returns MCP structured content with a published output schema.
`max_rows` (default 100, up to 1000) limits only the rows copied into the tool
result; `row_count` and `truncated` report the full result. SQL and rows are
returned only when the agent's own settings allow them (`show_sql_query`,
`show_db_result`); otherwise the result says so in `notes`. Errors from the API
are returned as MCP tool errors with the server's reason, for example
`Not permitted for agent NL2SQL_… (HTTP 403): This API key is not valid for this agent`.

## Install

You need Python 3.10 or later and a running Database Agent API (the
[local installation](../README.md#install) or your own deployment).

```sh
pip install "git+https://github.com/FutureSmart-AI/database-agent.git#subdirectory=mcp-server"
```

This installs the `database-agent-mcp` command. From a clone you can instead run
`pip install ./mcp-server`, or skip installing with
`uvx --from ./mcp-server database-agent-mcp`.

## Credentials

Use per-agent API keys. A key works only on the agent it was issued for and
cannot manage keys, collaborators, the database connection or the agent itself.
Issue one in the UI under **Share → API**, or with the operator key:

```sh
curl -s -X POST "http://127.0.0.1:18000/nl2sql/api/v1/agents/$AGENT_ID/api-keys" \
  -H "X-API-Key: $FASTAPI_SECRET_KEY" -H "Content-Type: application/json" -d '{}'
```

| Setting | Purpose |
|---|---|
| `DATABASE_AGENT_URL` | API root; default `http://127.0.0.1:18000/nl2sql/api`. For the hosted product use `https://futuresmart.ai/database-agent/api` with a key issued there. Plain HTTP is refused for non-loopback hosts unless `DATABASE_AGENT_ALLOW_INSECURE_HTTP=1` |
| `DATABASE_AGENT_AGENT_KEYS` | `AGENT_ID=KEY` pairs, comma- or newline-separated. Recommended |
| `DATABASE_AGENT_API_KEY` | Operator (master) key, `FASTAPI_SECRET_KEY`. Reaches every agent; only for a trusted single-operator installation |
| `DATABASE_AGENT_TIMEOUT_SECONDS` | Per-request timeout; default 180 |

If both are set, an agent's own key is used for that agent and the operator key
for the rest. The server reads these from its environment and never prints them.

## Claude Code

Add a `.mcp.json` to your project. Claude Code expands the environment variables
when it starts the server, so the file holds no key:

```json
{
  "mcpServers": {
    "database-agent": {
      "command": "database-agent-mcp",
      "env": {
        "DATABASE_AGENT_URL": "${DATABASE_AGENT_URL:-http://127.0.0.1:18000/nl2sql/api}",
        "DATABASE_AGENT_AGENT_KEYS": "${DATABASE_AGENT_AGENT_KEYS}"
      }
    }
  }
}
```

Set `DATABASE_AGENT_AGENT_KEYS` (for example `NL2SQL_1A2B3C4D=<key>`) in the
shell that starts Claude Code. To register the server for every project instead,
use `claude mcp add`; it stores the values you pass in your Claude Code
configuration file:

```sh
claude mcp add database-agent --scope user \
  -e DATABASE_AGENT_URL=http://127.0.0.1:18000/nl2sql/api \
  -e "DATABASE_AGENT_AGENT_KEYS=$AGENT_ID=$AGENT_KEY" \
  -- database-agent-mcp
```

`claude mcp list` should show `database-agent: database-agent-mcp - ✔ Connected`.
Then ask in Claude Code, for example with the agent from
[Try the sample](../README.md#try-the-sample):

> Using the database-agent tools, what is the total amount for each region in
> orders? Show the SQL and rows. Then ask a follow-up in the same conversation:
> which region has the higher total?

Claude Code calls `list_agents`, then `ask_database`, then `ask_database` again
with the returned `session_id`. The expected rows are **North: 250.00** and
**South: 200.00**, and the follow-up answers North. Claude Code asks permission
before using each tool unless you allow it.

Other MCP clients use the same command and environment variables over stdio.

## The API alternative

The tools add no capability the API lacks. To call the agent directly:

```sh
curl -s -X POST "http://127.0.0.1:18000/nl2sql/api/v1/agents/$AGENT_ID/chat?stream=false" \
  -H "X-API-Key: $AGENT_KEY" -H "Content-Type: application/json" \
  -d '{"query": "What is the total amount for each region in orders?", "debug_info": true}'
```

The response carries `response`, `session_id`, `chat_id`, `is_answered`,
`debug_info.sql_query`, `debug_info.db_result` (`columns`, `rows`, `row_count`)
and `chart_output`. Send a follow-up to
`POST /v1/agents/{id}/sessions/{session_id}/messages` with the same body. See
[api.md](api.md) and the OpenAPI reference for every field.

## Security notes

- The agent's source credentials should be a dedicated read-only database
  account. The adapter cannot widen what that account or the agent's table
  visibility allows; it only forwards questions.
- An agent only ever sees its own turns of a conversation: history and replays
  are read for that agent alone, and a `session_id` created on another agent
  returns HTTP 404 before any history is read or any model is called.
  Deployments running an API version older than this change do not perform
  that check.
- Saved conversations follow the agent's `show_sql_query` and `show_db_result`
  in the API itself, exactly as live answers do: a replay leaves out the SQL and
  rows the agent hides, and CSV export returns HTTP 403 when rows are hidden.
  Deployments running an API version older than this change return them; the
  adapter applies the same settings either way.
- An agent key can list and read every conversation on its own agent, not only
  the ones it created.

## Verification

`tests/mcp` checks the adapter through real MCP client sessions, in memory and
over stdio, against a synthetic API with the product's credential rules. CI runs
it with `tests/backend/test_session_scope.py`, which covers the session check,
saved-result replay and saved-conversation visibility in the API itself.

The integration was also run end to end on a disposable installation of this
branch (Compose stack, default model profile, the synthetic `sample_sales`
database with its read-only account) with two clients: the MCP Python SDK over
stdio, and Claude Code (`claude -p` with the `.mcp.json` above). That run covered:

- listing agents, asking with SQL, rows and a bar-chart suggestion, a follow-up
  in the same session, and reading the saved conversation (North 250.00,
  South 200.00);
- an agent configured to hide SQL and rows, live and saved;
- authorization failures: an unknown key (401), another agent's key (403), a
  session from another agent (404) and an agent with no configured key;
- read-only access: requests to delete, drop or update data produced no SQL,
  and the database still held its four original rows afterwards; a table the
  database account can read but the agent's table visibility excludes was not
  queried.

Charts are produced when the question asks for one ("Show a bar chart") and the
agent's chart setting allows it; `include_chart` sets that setting per question.
