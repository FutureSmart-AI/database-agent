/**
 * The Database Agent product's routes and the API calls behind them, in the one
 * shape `cy.intercept` wants: a glob that matches whatever origin the app is built
 * against (the dev server or the static preview locally, the real host in
 * staging).
 *
 * The UI routes moved to `/database-agent` with the rename; the service API
 * paths below keep `/nl2sql/api/v1` deliberately — that is the internal service
 * name and it is not renamed.
 *
 * Kept in step with `src/lib/routes.ts` and `src/data/api.ts` — those are the
 * source of truth.
 */

/** `src/lib/routes.ts`, with the trailing slash Next adds. */
const APP = "/database-agent";

/** The product's pre-rename prefix, kept alive by forwarding stubs. */
const LEGACY_APP = "/nl2sql";

export const ROUTES = {
  home: `${APP}/`,
  conversations: `${APP}/conversations/`,
  analytics: `${APP}/analytics/`,
  share: `${APP}/share/`,
  reports: `${APP}/batch-query-reports/`,
  settings: `${APP}/settings/`,
  usage: `${APP}/usage/`,
  credentials: `${APP}/credentials/`,
  /**
   * Retired URLs kept only as client-side hops to `home`: the product dropped
   * its `/dashboard` segment when the marketing page above it went away, and
   * then moved off `/nl2sql` when it was renamed Database Agent.
   */
  legacyDashboard: `${LEGACY_APP}/dashboard/`,
  legacyHome: `${LEGACY_APP}/`,
  legacyConversations: `${LEGACY_APP}/conversations/`,
} as const;

export type Route = (typeof ROUTES)[keyof typeof ROUTES];

/** Every agent-scoped rail destination, for the navigation sweep. */
export const AGENT_SCOPED: Array<{ route: Route; title: string }> = [
  { route: ROUTES.conversations, title: "Conversations" },
  { route: ROUTES.analytics, title: "Agent Analytics" },
  { route: ROUTES.share, title: "Share" },
  { route: ROUTES.reports, title: "Batch Query Reports" },
  { route: ROUTES.settings, title: "Settings" },
];

/**
 * Request matchers, as regular expressions rather than globs.
 *
 * A glob would be ambiguous here: minimatch reads `?` as "any single
 * character", so `**​/agents?*` also matches `/agents/shared` — and a spec that
 * waited on the agent list would happily resolve on the shared-agents call
 * instead. Regexes say exactly which route is meant, and match whichever origin
 * the app was built against (the local proxy in dev, app.futuresmart.ai in
 * staging).
 */
const id = "[^/?#]+";

export const API = {
  profile: /\/user\/me(\?|$)/,
  agents: new RegExp(`/nl2sql/api/v1/agents(\\?|$)`),
  sharedAgents: /$a/,
  /**
   * A single agent's registry row — what the agent dashboard's `AuthContext`
   * reads to decide the caller's role. `shared` is carved out because it is a
   * collection, not an id.
   */
  agent: new RegExp(`/nl2sql/api/v1/agents/${id}(\\?|$)`),
  agentConfig: new RegExp(`/nl2sql/api/v1/agents/${id}/config(\\?|$)`),
  providers: /\/nl2sql\/api\/v1\/models(\?|$)/,
  chat: new RegExp(`/nl2sql/api/v1/agents/${id}/chat(\\?|$)`),

  databases: new RegExp(`/nl2sql/api/v1/agents/${id}/databases(\\?|$)`),
  databasesCheck: new RegExp(`/nl2sql/api/v1/agents/${id}/databases/check`),
  databaseTest: /\/nl2sql\/api\/v1\/databases\/test(\?|$)/,
  tables: new RegExp(
    `/nl2sql/api/v1/agents/${id}/databases/${id}/tables(\\?|$)`,
  ),
  tableVisibility: new RegExp(
    `/nl2sql/api/v1/agents/${id}/databases/${id}/tables/${id}/visibility`,
  ),
  fewShot: new RegExp(
    `/nl2sql/api/v1/agents/${id}/databases/${id}/few-shot-examples`,
  ),
  /**
   * The node configuration is read from the service's whole `config` document,
   * not from a `/config/nodes` collection — `fetchNodes` in
   * `src/data/agents.ts`. Waiting on `/config/nodes` waits forever.
   */
  nodes: new RegExp(`/nl2sql/api/v1/agents/${id}/config(\\?|$)`),
  /** The write side, which *is* per node. */
  nodeConfig: new RegExp(`/nl2sql/api/v1/agents/${id}/config/nodes`),

  /** The NL2SQL service's own statistics — read by Usage, not by Analytics. */
  statistics: new RegExp(`/nl2sql/api/v1/agents/${id}/statistics(\\?|$)`),

  /**
   * The fleet grid — the one analytics route that is not per-agent, read by
   * Analytics when the URL names no agent.
   */
  analyticsOverview: /\/nl2sql\/api\/v1\/agents\/analytics\/overview(\?|$)/,

  /** The NL2SQL service's analytics — what the Analytics page reads. */
  scorecard: new RegExp(
    `/nl2sql/api/v1/agents/${id}/analytics/scorecard(\\?|$)`,
  ),
  trends: new RegExp(`/nl2sql/api/v1/agents/${id}/analytics/trends(\\?|$)`),
  queries: new RegExp(`/nl2sql/api/v1/agents/${id}/analytics/queries(\\?|$)`),
  failures: new RegExp(`/nl2sql/api/v1/agents/${id}/analytics/failures(\\?|$)`),
  /**
   * The dashboard service's analytics routes. Kept only so a spec can assert
   * they are *not* called: they are keyed by chat-registry ids and answer 403
   * for an `NL2SQL_…` agent.
   */
  dashboardScorecard: new RegExp(`/api/dashboard/v1/agents/${id}/scorecard`),
  dashboardTrends: new RegExp(`/api/dashboard/v1/agents/${id}/trends`),
  dashboardQueries: new RegExp(`/api/dashboard/v1/agents/${id}/queries`),
  /** API keys moved to the NL2SQL service with the rest of the product. */
  apiKeys: new RegExp(`/nl2sql/api/v1/agents/${id}/api-keys`),
  sessions: new RegExp(`/nl2sql/api/v1/agents/${id}/sessions(\\?|$)`),
  /** Reports moved to the NL2SQL service with the rest of the product. */
  reports: new RegExp(`/nl2sql/api/v1/agents/${id}/reports(\\?|$)`),
  reportRuns: new RegExp(
    `/nl2sql/api/v1/agents/${id}/reports/[^/?#]+/runs(\\?|$)`,
  ),
  reportRun: new RegExp(
    `/nl2sql/api/v1/agents/${id}/reports/[^/?#]+/runs/[^/?#]+(\\?|$)`,
  ),
  reportRunStatus: new RegExp(
    `/nl2sql/api/v1/agents/${id}/reports/[^/?#]+/runs/[^/?#]+/status`,
  ),
  /**
   * The dashboard service's report routes. Kept only so a spec can assert they
   * are *not* called: they take `?agent_id=` and reject an `NL2SQL_…` id.
   */
  dashboardReports: /\/api\/dashboard\/v1\/reports/,

  /**
   * The usage service's analytics query. The Usage screen no longer reads it —
   * kept so a spec can assert it is *not* called.
   */
  usageAnalyticsQuery: /\/api\/usage\/v1\/analytics\/query/,

  /**
   * The workspace's provider keys, which moved to the NL2SQL service with the
   * rest of the product — `{owner_id}` is the literal `me`. The usage service's
   * `/api/usage/v1/owners/…` are kept so a spec can assert they are *not*
   * called; the catch-all in `stubs.ts` would otherwise answer them silently.
   */
  /**
   * Everything the Usage & Limits screen reads, all on the NL2SQL service.
   *
   * `ownerLimits` is the whole Limits tab in one read and carries
   * `token_rate_usd`, which prices every cost figure on the screen — no usage
   * route returns a cost. The other three are the query routes; they are sent
   * the viewer's email rather than `me`, which they answer with an empty result
   * set.
   *
   * `ownerUsageStatus` is the endpoint this screen used to read, kept so a spec
   * can assert it is *not* called any more.
   */
  ownerLimits: /\/nl2sql\/api\/v1\/owners\/[^/?#]+\/limits(\?|$)/,
  usageAggregate: /\/nl2sql\/api\/v1\/aggregate(\?|$)/,
  usageTrend: /\/nl2sql\/api\/v1\/trend(\?|$)/,
  usageEvents: /\/nl2sql\/api\/v1\/events(\?|$)/,
  ownerUsageStatus: /\/nl2sql\/api\/v1\/owners\/[^/?#]+\/usage\/status(\?|$)/,

  ownerProviders: /\/nl2sql\/api\/v1\/owners\/providers(\?|$)/,
  ownerCredentials: /\/nl2sql\/api\/v1\/owners\/[^/?#]+\/credentials(\?|$)/,
  ownerCredential:
    /\/nl2sql\/api\/v1\/owners\/[^/?#]+\/credentials\/[^/?#]+(\?|$)/,
  usageOwnerProviders: /\/api\/usage\/v1\/owners\/providers/,
  usageOwnerCredentials: /\/api\/usage\/v1\/owners\/[^/?#]+\/credentials/,
} as const;
