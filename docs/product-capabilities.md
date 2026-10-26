# Product capabilities

What FutureSmart Database Agent does today, where each capability is available, and where
to read more. This page is a map, not the manual: each section links to the detailed guide.
Status as of 2026-10-26.

**Two ways to run it**

- **Hosted**: [futuresmart.ai/solutions/database-agent](https://futuresmart.ai/solutions/database-agent)
  (application at `app.futuresmart.ai/database-agent/`, API root
  `https://futuresmart.ai/database-agent/api`). Sign in with a FutureSmart account.
- **Standalone**: this repository on your own machine or cloud with Docker Compose and one
  `OPENAI_API_KEY` ([Install](../README.md#install)). One operator signs in with the generated
  password; no FutureSmart account is needed.

## At a glance

| Capability | Hosted | Standalone | Read more |
|---|---|---|---|
| Ask questions in plain English; see SQL, rows and answer | Yes | Yes | [README](../README.md#what-you-can-do) |
| PostgreSQL and MySQL sources (read-only account recommended) | Yes | Yes | [Known limits](../README.md#known-limits) |
| Charts (bar, line, stacked and others) beside the table | Yes | Yes | [Architecture](architecture.md) |
| Follow-up questions and saved conversations | Yes | Yes | [API](api.md) |
| Full logs: per-operation model, time, tokens and estimated cost | Yes | Yes | [Cost and latency](#cost-latency-and-evaluation) |
| Free sample-data agent (Cedar Lane e-commerce) | Yes | Local `sample_sales` database instead | [Sample data](#sample-data-and-suggested-workflows) |
| Report a problem on an answer | Yes | In the source; not separately verified standalone | — |
| REST API with OpenAPI reference | Yes | Yes | [API](api.md), [developer docs](https://futuresmart.ai/docs/database-agent) |
| Agent-scoped API keys | Yes (Share → API → Generate API key) | Yes (`POST /v1/agents/{id}/api-keys`) | [API](api.md) |
| MCP server (Claude Code and other MCP clients) | Yes, over the hosted API | Yes, over the local API | [MCP](mcp.md), [hosted MCP setup](https://futuresmart.ai/docs/database-agent/mcp) |
| Your own provider keys instead of the platform key | Yes, per account (Credentials page) | Always your own keys | [Configuration](configuration.md) |
| Model profile, per-operation overrides, other chat providers | Platform-managed | Yes (`backend/model_config.json`) | [Model configuration](model-configuration.md) |
| Model evaluation (accuracy, latency, cost per configuration) | — | Yes (`tests/evaluation/model_eval`) | [Evaluation README](../tests/evaluation/model_eval/README.md) |
| Usage, analytics and batch query report pages | Yes | In the source; not separately verified standalone | — |
| Deploy to AWS (ECS/Fargate API, static UI) | — | Yes | [AWS deployment](aws-deployment.md) |

## Using it

### UI

1. Create an agent: name it, connect a PostgreSQL or MySQL database with a read-only account,
   test the connection. The wizard discovers tables and writes descriptions you can edit,
   including which tables the agent may use.
2. Ask a question. Each answer shows the prose answer, the SQL, the rows and, where it fits, a
   chart. Ask follow-ups in the same conversation; conversations are saved in the sidebar.
3. **Full logs** on an answer lists every operation the answer paid for (routing, table
   selection, SQL generation, execution, checks, chart, final answer, other model calls) with
   its model, time, tokens and estimated cost, under a total that matches the answer.
4. **Share → API** (hosted, your own agents) shows the agent's chat endpoint and generates an
   agent-scoped key. Share is disabled on example agents.

### REST API

The UI calls the same API. Hosted root `https://futuresmart.ai/database-agent/api`, local root
`http://127.0.0.1:18000/nl2sql/api`, each with `/docs` and `/openapi.json`. Main routes: create
an agent, attach a database, set table descriptions and visibility, issue an agent key, chat
(streaming or not), follow-up messages, list and read saved conversations, export results.
Each chat response carries a `usage` block (below). Full route list: [API](api.md); hosted
quickstart, keys, streaming and errors: [developer docs](https://futuresmart.ai/docs/database-agent).

### MCP

`mcp-server/` is a thin adapter over the API with five tools: `list_agents`, `ask_database`
(with `session_id` for follow-ups), `list_conversations`, `get_conversation`. It holds no
database credentials and runs no SQL; key scope, table visibility and SQL controls stay in the
API. Install and Claude Code setup: [MCP](mcp.md). Verified against the hosted API from a
script on 2026-10-25 (4 tools, a saved conversation with rows); a hands-on Claude Code session
with a freshly generated agent key is not yet recorded (see [Not yet available](#not-yet-available-or-not-yet-verified)).

## Models and keys

- **Single key.** The shipped profile `futuresmart-recommended-v1` needs only
  `OPENAI_API_KEY`: `gpt-6.1-sol` for routing, table selection, SQL generation and pandas
  planning; `gpt-6-luna` for descriptions, presentation, charts and follow-ups;
  `text-embedding-3-small` for embeddings.
- **Overrides.** `backend/model_config.json` can override the model per operation.
- **Other chat providers.** `single_provider` switches chat operations to Google, Groq,
  Anthropic, DeepSeek or MiniMax with that provider's key. Embeddings stay on OpenAI, so this
  needs an OpenAI key too. There is no automatic fallback to another model after a failure.
- **Hosted keys.** Each hosted account uses either its own provider keys (Credentials page) or
  the platform key. An account on its own keys gets a clear error, never a silent fallback,
  when its key is missing.

Details, constraints and vector compatibility: [Model configuration](model-configuration.md).

## Sample data and suggested workflows

- **Hosted:** *Try with sample data* opens the free Cedar Lane agent: a year (2025) of
  synthetic customers, products, orders, payments and returns for an online shop. Each account
  gets 20 questions per rolling 24 hours and 100 in total; verified futuresmart.ai and
  aidemos.com accounts are unlimited. Good first questions: top five customers by spend, orders
  per month in 2025, then a follow-up such as "only non-cancelled orders".
- **Standalone:** connect the bundled `sample_sales` database and check the bar chart against
  North 250.00 and South 200.00 ([Try the sample](../README.md#try-the-sample)).
- **Your data:** create a dedicated read-only database user, connect it, review the table
  descriptions, then ask; check the SQL and rows of anything you rely on.
- **From your software or Claude Code:** generate an agent key, call the chat endpoint or add
  the MCP server.

## Cost, latency and evaluation

- **Per answer.** Every chat response includes `usage`: `latency_ms`, input and output tokens,
  `estimated_cost_usd` and a `nodes` list (operation, model, time, tokens, cost) covering every
  model call, including ones no named step records. Cost uses the dated list prices in
  `backend/model_profiles/prices.json`, with cached input at the cached rate; `cost_complete`
  is false if any model is unpriced. The block is stored with each turn and returned on saved
  replay. It is an estimate from list prices, not a provider invoice.
- **Model evaluation.** `tests/evaluation/model_eval` asks 18 questions over two synthetic
  databases through the real API for each configuration and reports correctness (LLM judge plus
  exact table match), SQL validity, latency and cost, with LangSmith experiments.
  First result (2026-10-25): shipped profile 70/72, `gpt-6-luna` for the SQL operations 65/72
  at about one seventh of the cost ([evidence](improvements/evidence/2026-10-25-model-evaluation.json)).
  Runs are on demand only: locally with the commands in the
  [evaluation README](../tests/evaluation/model_eval/README.md), or in the development
  repository's **Model evaluation** GitHub Actions workflow (manual dispatch). The weekly
  schedule was switched off on 2026-10-26.
- **Provider-free checks.** `docker compose run --rm evaluate --fixture-only` checks the sample
  and read-only grants without a model call; [Development](development.md) covers the
  reliability suites.

## Limitations

- The SQL execution path is not a general sandbox: use read-only source credentials and review
  generated queries. MySQL is accepted on port 3306 only.
- Standalone login is for a single operator; there are no user accounts or roles.
- Hosted own-key behaviour was verified on one bounded journey, not as a load or
  multi-tenant security assessment.
- Only the OpenAI profile is a one-key install; other providers have no published capability
  matrix.
- The free Cedar Lane sample agent and its question allowance are hosted only.
- Results from the evaluation are evidence about its 18 questions, not general accuracy.

## Not yet available or not yet verified

- A hands-on MCP session in Claude Code with a key generated from Share → API, and the full
  API-key onboarding journey end to end.
- Choosing model candidates across providers automatically (comparable, cheaper, more capable).
- Running a model evaluation on demand from the product instead of from the repository.
- Shared website widget assets and the retired external report-consumer lane.

Improvement history and the research behind past fixes: [improvements](improvements/README.md).
