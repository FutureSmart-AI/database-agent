/**
 * Every HTTP endpoint this app calls, verified against the live backend.
 *
 * NL2SQL is the source of truth for this product. Every agent-scoped route is
 * keyed by its NL2SQL `agent_id`.
 */
export const APIS = {
  /** NL2SQL service — the agent itself. */
  NL2SQL_AGENTS: "/nl2sql/api/v1/agents",
  NL2SQL_AGENT: "/nl2sql/api/v1/agents/{service_id}",
  /** Databases discoverable on an RDS host (POST — it takes credentials). */
  RDS_LIST: "/nl2sql/api/v1/databases/rds/list",
  /** Add several databases at once. */
  DATABASES_BULK: "/nl2sql/api/v1/agents/{service_id}/databases/bulk",

  /**
   * NL2SQL service — asking a question, and the sessions that answering opens.
   *
   * `?stream=true` makes the route answer `text/event-stream`.
   */
  NL2SQL_CHAT: "/nl2sql/api/v1/agents/{service_id}/chat",
  NL2SQL_SESSIONS: "/nl2sql/api/v1/agents/{service_id}/sessions",
  /** GET reads the thread; PATCH renames it; DELETE removes it. */
  NL2SQL_SESSION: "/nl2sql/api/v1/agents/{service_id}/sessions/{session_id}",
  NL2SQL_FEEDBACK: "/nl2sql/api/v1/agents/{service_id}/feedback",

  /** NL2SQL service — configuration. */
  NL2SQL_CONFIG: "/nl2sql/api/v1/agents/{service_id}/config",
  NL2SQL_NODES: "/nl2sql/api/v1/agents/{service_id}/config/nodes",
  NL2SQL_NODE: "/nl2sql/api/v1/agents/{service_id}/config/nodes/{node_name}",
  NL2SQL_PARAMS: "/nl2sql/api/v1/agents/{service_id}/config/params",
  /** Models the NL2SQL service currently exposes. */
  NL2SQL_MODELS: "/nl2sql/api/v1/models",
  /** Requests, tokens and latencies the NL2SQL service records for an agent. */
  NL2SQL_STATISTICS: "/nl2sql/api/v1/agents/{service_id}/statistics",
  NL2SQL_INVITATIONS: "/nl2sql/api/v1/agents/{agent_id}/invitations",
  NL2SQL_INVITATION: "/nl2sql/api/v1/agents/{agent_id}/invitations/{email}",
  NL2SQL_WIDGET_SETTINGS: "/nl2sql/api/v1/agents/{agent_id}/widget/settings",
  NL2SQL_WIDGET_ICONS: "/nl2sql/api/v1/widgets/icons/defaults",
  NL2SQL_WIDGET_AVATARS: "/nl2sql/api/v1/widgets/avatars/defaults",

  /** NL2SQL service — databases. */
  DATABASES: "/nl2sql/api/v1/agents/{service_id}/databases",
  DATABASE: "/nl2sql/api/v1/agents/{service_id}/databases/{db_id}",
  DATABASES_CHECK: "/nl2sql/api/v1/agents/{service_id}/databases/check",
  DATABASE_TEST: "/nl2sql/api/v1/databases/test",
  DATABASE_STATUS:
    "/nl2sql/api/v1/agents/{service_id}/databases/{db_id}/status",
  DATABASE_DESCRIPTION:
    "/nl2sql/api/v1/agents/{service_id}/databases/{db_id}/description",
  DATABASE_DESCRIPTION_GENERATE:
    "/nl2sql/api/v1/agents/{service_id}/databases/{db_id}/description/generate",
  DATABASE_DESCRIPTION_POLL:
    "/nl2sql/api/v1/agents/{service_id}/databases/{db_id}/description/generate/{job_id}",

  /** NL2SQL service — tables and examples. */
  TABLES: "/nl2sql/api/v1/agents/{service_id}/databases/{db_id}/tables",
  TABLE_VISIBILITY:
    "/nl2sql/api/v1/agents/{service_id}/databases/{db_id}/tables/{table_name}/visibility",
  TABLES_GENERATE:
    "/nl2sql/api/v1/agents/{service_id}/databases/{db_id}/tables/generate",
  TABLES_GENERATE_POLL:
    "/nl2sql/api/v1/agents/{service_id}/databases/{db_id}/tables/generate/{job_id}",
  /** One table's description, generated synchronously. */
  TABLE_GENERATE:
    "/nl2sql/api/v1/agents/{service_id}/databases/{db_id}/tables/{table_name}/generate",
  FEW_SHOT:
    "/nl2sql/api/v1/agents/{service_id}/databases/{db_id}/few-shot-examples",

  /**
   * NL2SQL service — batch query reports. Every route is agent-scoped by path
   * (the dashboard service takes `?agent_id=` instead and answers 403 for an
   * `NL2SQL_…` id, which is why this page used to say reports were unavailable).
   */
  REPORTS: "/nl2sql/api/v1/agents/{agent_id}/reports",
  REPORT_SETTINGS: "/nl2sql/api/v1/agents/{agent_id}/reports/settings",
  REPORT: "/nl2sql/api/v1/agents/{agent_id}/reports/{report_id}",
  REPORT_RUNS: "/nl2sql/api/v1/agents/{agent_id}/reports/{report_id}/runs",
  REPORT_RUN:
    "/nl2sql/api/v1/agents/{agent_id}/reports/{report_id}/runs/{run_id}",
  REPORT_RUN_STATUS:
    "/nl2sql/api/v1/agents/{agent_id}/reports/{report_id}/runs/{run_id}/status",
  REPORT_RUN_EXPORT:
    "/nl2sql/api/v1/agents/{agent_id}/reports/{report_id}/runs/{run_id}/export",
  REPORT_RUN_CANCEL:
    "/nl2sql/api/v1/agents/{agent_id}/reports/{report_id}/runs/{run_id}/cancel",

  /**
   * NL2SQL service — everything the Usage & Limits screen reads.
   *
   * These four are the whole surface. The usage service's own
   * `POST /api/usage/v1/analytics/query` used to back this screen because
   * `/v1/aggregate` returned no cost and no per-day series; `/v1/trend` now
   * serves the series, and cost is derived from `token_rate_usd` on
   * `/v1/owners/{id}/limits`, so there is no reason left to read two services
   * for one screen — and every reason not to, since two sources for one figure
   * is two figures that can disagree.
   *
   * `USAGE_AGGREGATE` groups by any of operation, label, agent_id, key_type,
   * model, provider, phase. Anything else is a 422, not a silent ignore — and
   * `service_type` is deliberately not in that list, because every row here is
   * `nl2sql` and the group would always be one.
   *
   * `USAGE_TREND` takes the same filters plus `days` (1–366) and
   * `bucket` (day | week | month). The series is dense: an empty bucket comes
   * back as `event_count: 0`, and it must be plotted, not skipped.
   *
   * `OWNER_LIMITS` is the whole Limits tab in one read, with `lifted`,
   * `enforced` and `percent` already resolved server-side — see `PlanLimits`.
   *
   * `USAGE_EVENTS` is the raw event log behind every aggregate.
   *
   * `{owner_id}` accepts the literal `me` on a browser session.
   */
  USAGE_AGGREGATE: "/nl2sql/api/v1/aggregate",
  USAGE_TREND: "/nl2sql/api/v1/trend",
  USAGE_EVENTS: "/nl2sql/api/v1/events",
  OWNER_LIMITS: "/nl2sql/api/v1/owners/{owner_id}/limits",

  /**
   * NL2SQL service — the workspace's own provider keys ("Add Credentials").
   *
   * Same four shapes the usage service serves at `/api/usage/v1/owners/…`, with
   * identical bodies, on this service's namespace. The request layer stays
   * shared with the agent dashboard (`@/platform/lib/api-keys/api` takes the routes
   * as an argument); only the screen is this product's own.
   *
   * `{owner_id}` accepts the literal `me` for the signed-in session, so nothing
   * here needs the viewer's email. There is deliberately no `…/internal` route:
   * it answers with the decrypted key, is master-key only, and 403s a browser
   * session even for that session's own key.
   */
  OWNER_PROVIDERS: "/nl2sql/api/v1/owners/providers",
  OWNER_CREDENTIALS: "/nl2sql/api/v1/owners/{owner_id}/credentials",
  OWNER_CREDENTIAL: "/nl2sql/api/v1/owners/{owner_id}/credentials/{provider}",

  /**
   * NL2SQL service — per-agent API keys. Issue, list and revoke all live on the
   * NL2SQL service; the dashboard routes answer 403 for an `NL2SQL_…` id.
   */
  API_KEYS: "/nl2sql/api/v1/agents/{agent_id}/api-keys",
  API_KEY: "/nl2sql/api/v1/agents/{agent_id}/api-keys/{api_key}",

  /**
   * NL2SQL service — analytics.
   *
   * The same six shapes the agent dashboard's analytics page reads, on the
   * NL2SQL service's own namespace and keyed by the `NL2SQL_…` id. The
   * dashboard's `/api/dashboard/v1/agents/{id}/scorecard|trends|queries` are
   * keyed by chat-registry ids and answer 403 here, which is why these exist.
   *
   * `scorecard` alone renders Overview, Quality, Performance and Cost — moving
   * between those four tabs issues no request. `failures` has no dashboard
   * equivalent at all.
   */
  ANALYTICS_OVERVIEW: "/nl2sql/api/v1/agents/analytics/overview",
  ANALYTICS_SCORECARD: "/nl2sql/api/v1/agents/{agent_id}/analytics/scorecard",
  ANALYTICS_TRENDS: "/nl2sql/api/v1/agents/{agent_id}/analytics/trends",
  ANALYTICS_QUERIES: "/nl2sql/api/v1/agents/{agent_id}/analytics/queries",
  ANALYTICS_FAILURES: "/nl2sql/api/v1/agents/{agent_id}/analytics/failures",
  ANALYTICS_SYNC_COSTS: "/nl2sql/api/v1/agents/{agent_id}/analytics/sync-costs",
} as const;
