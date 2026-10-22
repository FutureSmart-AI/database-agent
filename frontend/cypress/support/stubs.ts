import { API } from "./routes";

/**
 * The minimum stubbed backend the app needs to boot.
 *
 * Used by the ungated boot smoke only. The rest of the suite runs against the
 * live backend on purpose — this exists so CI, which has no SSO session, still
 * checks something real: that the app mounts, routes, and paints its shell.
 *
 * Without a stubbed `/user/me` there is nothing to check at all —
 * `RequireSession` sends the browser to the SSO origin, and a cross-origin
 * navigation to a host that is not running is not a test, it is a hang.
 */

export const STUB_AGENT_ID = "AGENT_CYPRESS_SMOKE";
export const STUB_SERVICE_ID = "NL2SQL_CYPRESS";
export const STUB_AGENT_NAME = "Cypress Smoke Agent";
export const STUB_DB_NAME = "cypress_smoke_db";

/** An agent somebody else owns and shared with the caller. */
export const STUB_SHARED_AGENT_ID = "AGENT_CYPRESS_SHARED";
export const STUB_SHARED_AGENT_NAME = "Cypress Shared Agent";
export const STUB_SHARED_OWNER = "someone.else@futuresmart.ai";

const profile = { email: "cypress@futuresmart.ai", name: "Cypress" };

const registryAgent = {
  agent_id: STUB_AGENT_ID,
  owner_id: profile.email,
  role: null,
  created_at: "2026-01-01T00:00:00Z",
  last_modified: "2026-01-02T00:00:00Z",
  services: [
    { service_type: "nl2sql", service_id: STUB_SERVICE_ID, status: "enabled" },
  ],
  config: {
    agent_params: {
      agent_name: STUB_AGENT_NAME,
      show_sources: true,
      follow_up: true,
      chart_output: true,
      memory_enabled: false,
      global_memory: false,
      raw_response: false,
      voice_input: false,
      voice_output: false,
      is_public: false,
      fullscreen_is_public: false,
      allowed_domains: [],
      suggested_questions: ["How many orders shipped late last month?"],
      default_language: null,
      greet_message: "Ask a question about your data in plain English.",
    },
  },
};

const sharedAgent = {
  ...registryAgent,
  agent_id: STUB_SHARED_AGENT_ID,
  owner_id: STUB_SHARED_OWNER,
  role: "editor",
  services: [
    {
      service_type: "nl2sql",
      service_id: "NL2SQL_CYPRESS_SHARED",
      status: "enabled",
    },
  ],
  config: {
    agent_params: {
      ...registryAgent.config.agent_params,
      agent_name: STUB_SHARED_AGENT_NAME,
    },
  },
};

const database = {
  db_id: "DB_CYPRESS",
  db_name: STUB_DB_NAME,
  db_host: "db.cypress.internal",
  db_user: "analytics_ro",
  db_port: 5432,
  db_engine: "postgresql",
  description: "Smoke-test database.",
  description_status: "ready",
  description_source: "manual",
  description_updated_at: "2026-01-02T00:00:00Z",
  is_active: true,
  status: "connected",
  table_count: 3,
  db_password: "***",
};

/** Everything the shell and its views ask for on first paint. */
export function stubBackend(): void {
  // Registered first on purpose: Cypress matches the *last* declared route, so
  // this is the fallback every specific stub below overrides. Anything the app
  // reaches for that this file has not thought of answers empty rather than
  // erroring the page — the smoke checks the shell, not the data.
  cy.intercept({ url: /\/api\/(chat|dashboard|usage)\/v1\// }, { body: {} });

  cy.intercept("GET", API.profile, { statusCode: 200, body: profile }).as(
    "profile",
  );
  cy.intercept("GET", API.agents, {
    statusCode: 200,
    body: { data: [registryAgent] },
  }).as("agents");
  cy.intercept("GET", API.sharedAgents, {
    statusCode: 200,
    body: { data: [sharedAgent] },
  }).as("shared");
  cy.intercept("GET", API.agent, (req) => {
    req.reply({
      statusCode: 200,
      body: req.url.includes(STUB_SHARED_AGENT_ID)
        ? sharedAgent
        : registryAgent,
    });
  }).as("agent");
  cy.intercept("GET", API.agentConfig, {
    statusCode: 200,
    body: registryAgent,
  });
  cy.intercept("GET", API.providers, { statusCode: 200, body: { data: [] } });
  cy.intercept("GET", API.databases, {
    statusCode: 200,
    body: { data: [database] },
  }).as("databases");
  cy.intercept("GET", API.tables, { statusCode: 200, body: { data: [] } });
  cy.intercept("GET", API.fewShot, { statusCode: 200, body: { data: [] } });
  cy.intercept("GET", API.nodes, { statusCode: 200, body: { data: [] } });
  cy.intercept("GET", API.apiKeys, { statusCode: 200, body: { data: [] } });
  cy.intercept("GET", API.reports, { statusCode: 200, body: { data: [] } });
  // The usage service's analytics query, which this product no longer reads.
  // Still answered so a stray call cannot reach the network and 401 the session.
  cy.intercept("POST", API.usageAnalyticsQuery, {
    statusCode: 200,
    body: { groups: [], totals: null, daily: [] },
  }).as("usageAnalyticsQuery");
  // A workspace whose agents have never been asked anything: the documented
  // first-run state, and what makes Analytics fall back to the agent picker.
  cy.intercept("GET", API.analyticsOverview, {
    statusCode: 200,
    body: {
      total_agents: 0,
      summary: { total_queries: 0, total_cost: 0, cost_complete: true },
      agents: [],
    },
  }).as("analyticsOverview");
  cy.intercept("GET", API.scorecard, { statusCode: 404, body: {} });
  cy.intercept("GET", API.trends, { statusCode: 404, body: {} });
  cy.intercept("GET", API.queries, {
    statusCode: 200,
    body: { queries: [], total_matching: 0 },
  }).as("queries");
  // The Limits tab, on the NL2SQL service — one read for the whole tab, with
  // every judgement already resolved server-side. The fixture keeps one row of
  // each kind the panel has to draw differently, because they are drawn
  // differently on purpose:
  //
  //   agents               a ceiling that applies      -> a bar
  //   databases_per_agent  `limit: null`               -> NO bar, "no limit"
  //   queries_per_day      the one `enforced` row      -> a bar, and the only
  //                                                       row that can banner
  //   tokens               `lifted` by an own key      -> NO bar, ceiling
  //                                                       still stated
  //
  // `exceeded` is empty: the blocking state is one a spec opts into rather than
  // the default every other spec has to look past. `token_rate_usd` is what
  // prices every cost figure on the screen.
  cy.intercept("GET", API.ownerLimits, {
    statusCode: 200,
    body: {
      owner_id: "me",
      tier: { name: "Free", tier_type: "free", is_default: true },
      billing_window: {
        days: 30,
        start: "2026-07-27T00:00:00+00:00",
        end: "2026-08-26T00:00:00+00:00",
      },
      own_credentials: ["openai"],
      token_rate_usd: 3.8e-6,
      groups: [
        {
          group: "Workspace",
          items: [
            {
              key: "agents",
              label: "Agents you can create",
              used: 1,
              limit: 3,
              unit: "agents",
              maximum: "3 agents on Free",
              note: "Every database agent in this workspace counts, active or paused.",
              lifted_by: [],
              held: [],
              missing: [],
              lifted: false,
              percent: 33.3,
              raises: "plan",
              enforced: false,
            },
            {
              key: "databases_per_agent",
              label: "Databases on a single agent",
              used: 2,
              limit: null,
              unit: "databases",
              maximum:
                "No limit on how many databases one agent routes between",
              note: "Your largest agent right now.",
              lifted_by: [],
              held: [],
              missing: [],
              lifted: false,
              percent: null,
              raises: "plan",
              enforced: false,
            },
          ],
        },
        {
          group: "Requests, tokens and cost",
          items: [
            {
              key: "queries_per_day",
              label: "Chat requests per day",
              used: 4,
              limit: 100,
              unit: "requests",
              maximum: "100 requests per rolling 24 hours",
              note: "Questions asked across every agent.",
              lifted_by: ["google", "openai"],
              held: ["openai"],
              missing: ["google"],
              lifted: false,
              percent: 4,
              raises: "plan-or-own-keys",
              enforced: true,
            },
            {
              key: "tokens",
              label: "Total tokens this billing period",
              used: 381440,
              limit: 2000000,
              unit: "tokens",
              maximum: "2,000,000 tokens per billing period on Free",
              note: "Input plus output across every model that served a request.",
              lifted_by: ["openai"],
              held: ["openai"],
              missing: [],
              lifted: true,
              percent: null,
              raises: "own-keys",
              enforced: false,
            },
          ],
        },
      ],
      exceeded: [],
    },
  }).as("ownerLimits");
  // The query routes. `groups` carries the dimension the caller grouped by, so
  // one fixture cannot serve them all — the aggregate answers by `group_by`,
  // and a grouping it has nothing for comes back empty rather than wrong.
  cy.intercept("GET", API.usageAggregate, (req) => {
    const grouped = req.query.group_by;
    const by = Array.isArray(grouped)
      ? grouped.join(",")
      : String(grouped ?? "");
    const metrics = (total: number, input: number, output: number) => [
      {
        metric_name: "total_tokens",
        total,
        avg: total,
        min: 0,
        max: total,
        count: 1,
      },
      {
        metric_name: "input_tokens",
        total: input,
        avg: input,
        min: 0,
        max: input,
        count: 1,
      },
      {
        metric_name: "output_tokens",
        total: output,
        avg: output,
        min: 0,
        max: output,
        count: 1,
      },
    ];
    const groups =
      by === "key_type"
        ? [
            {
              key_type: "platform-key",
              event_count: 42,
              metrics: metrics(381440, 300000, 81440),
            },
            {
              key_type: "owner-key",
              event_count: 8,
              metrics: metrics(40000, 32000, 8000),
            },
          ]
        : by === "operation"
          ? [
              {
                operation: "llm_call",
                event_count: 40,
                metrics: metrics(421440, 332000, 89440),
              },
              { operation: "db_query", event_count: 6, metrics: [] },
              { operation: "code_execution", event_count: 4, metrics: [] },
            ]
          : by === "agent_id"
            ? [
                {
                  agent_id: "NL2SQL_STUB",
                  event_count: 50,
                  metrics: metrics(421440, 332000, 89440),
                },
              ]
            : by === "label"
              ? [
                  {
                    label: "sql_generation",
                    event_count: 50,
                    metrics: metrics(421440, 332000, 89440),
                  },
                ]
              : by === "phase"
                ? [{ phase: "Answering", event_count: 50, metrics: [] }]
                : by === "model,provider"
                  ? [
                      {
                        model: "gpt-5.4-mini",
                        provider: "openai",
                        event_count: 40,
                        metrics: metrics(421440, 332000, 89440),
                      },
                      // `model: null` is real data, not an error.
                      {
                        model: null,
                        provider: null,
                        event_count: 10,
                        metrics: [],
                      },
                    ]
                  : [];
    req.reply({ statusCode: 200, body: { group_by: by.split(","), groups } });
  }).as("usageAggregate");
  // Dense and oldest-first, as the service sends it: an empty bucket is
  // `event_count: 0`, and the chart plots it rather than skipping it.
  cy.intercept("GET", API.usageTrend, {
    statusCode: 200,
    body: {
      bucket: "day",
      bucket_days: 1,
      days: 30,
      window_start: "2026-07-27T00:00:00+00:00",
      window_end: "2026-08-26T00:00:00+00:00",
      series: [
        {
          bucket_start: "2026-08-24T00:00:00+00:00",
          bucket_end: "2026-08-25T00:00:00+00:00",
          event_count: 0,
          metrics: {},
        },
        {
          bucket_start: "2026-08-25T00:00:00+00:00",
          bucket_end: "2026-08-26T00:00:00+00:00",
          event_count: 50,
          metrics: {
            total_tokens: 421440,
            input_tokens: 332000,
            output_tokens: 89440,
          },
        },
      ],
    },
  }).as("usageTrend");
  cy.intercept("GET", API.usageEvents, {
    statusCode: 200,
    body: { total_count: 0, limit: 50, offset: 0, events: [] },
  }).as("usageEvents");
  // Credentials, on the NL2SQL service. `/providers` carries no
  // `document_and_web_providers` — the service has no document-parsing or
  // web-scraping path — and a stored key comes back masked, never in full.
  cy.intercept("GET", API.ownerProviders, {
    statusCode: 200,
    body: { llm_providers: ["openai", "anthropic", "google"] },
  }).as("ownerProviders");
  cy.intercept("GET", API.ownerCredentials, {
    statusCode: 200,
    body: {
      status: "success",
      data: [
        {
          provider: "openai",
          mask: "sk-...48sA",
          is_valid: true,
          updated_at: "2026-08-20T09:14:02+00:00",
        },
      ],
    },
  }).as("ownerCredentials");
  // Registered so a spec can assert the page no longer reads the usage service.
  cy.intercept("GET", API.usageOwnerProviders, {
    statusCode: 200,
    body: {},
  }).as("usageOwnerProviders");
  cy.intercept("GET", API.usageOwnerCredentials, {
    statusCode: 200,
    body: {},
  }).as("usageOwnerCredentials");
}
