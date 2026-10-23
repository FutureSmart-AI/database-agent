# database-agent-mcp

MCP server for [FutureSmart Database Agent](https://github.com/FutureSmart-AI/database-agent).
It lets MCP-compatible applications such as Claude Code list your Database Agent
agents, ask natural-language database questions, get back the answer, generated
SQL, structured rows and chart metadata, continue conversations, and read saved
results.

It is a thin adapter over the Database Agent REST API, using an existing API
credential. The API keeps authentication, query limits, model configuration,
table visibility, SQL access controls and execution.

```sh
pip install "git+https://github.com/FutureSmart-AI/database-agent.git#subdirectory=mcp-server"
claude mcp add database-agent --scope user \
  -e DATABASE_AGENT_URL=http://127.0.0.1:18000/nl2sql/api \
  -e "DATABASE_AGENT_AGENT_KEYS=$AGENT_ID=$AGENT_KEY" \
  -- database-agent-mcp
```

See [docs/mcp.md](../docs/mcp.md) for tools, credentials, configuration, the
Claude Code `.mcp.json` example and the equivalent direct API calls.
