import type {
  AnalyticsWindow,
  NodeDatum,
  QueryLogResponse,
  QueryRow,
  Scorecard,
  ScorecardNode,
  ServiceCall,
  TrendsResponse,
} from "@/platform/analytics/types";

/**
 * NL2SQL analytics responses → the shapes the agent dashboard's analytics
 * components already consume.
 *
 * The two services answer the same information; they disagree on a handful of
 * fields, and the dashboard's types mark several of those required. Rather than
 * loosen types the main product relies on, or fork the tabs, the differences are
 * reconciled once, here, and every chart and table above is reused untouched.
 *
 * What actually differs (verified against `analytics-api-for-ui.md`, 2026-08-14):
 *
 * | dashboard field            | NL2SQL           | resolved by            |
 * | -------------------------- | ---------------- | ---------------------- |
 * | `name`, `previous_since`   | absent           | null / derived         |
 * | `quality.budget_exhausted` | absent           | 0 (no token budget)    |
 * | `trend`                    | absent           | omitted; page derives  |
 * | `QueryRow.services_used`   | `nodes_used`     | `["nl2sql"]` (below)   |
 * | `metrics.service_calls`    | absent           | synthesized from       |
 * |                            |                  | `sql_exec_ms`          |
 * | `NodeDatum.latency_ms`     | `avg_latency_ms` | mapped                 |
 * | `NodeDatum.input_cost`     | absent           | 0                      |
 *
 * Nothing here invents a measurement: every filled field is either a constant
 * that is true for this product (one service), a rename, or a zero for a
 * quantity the service does not meter. Values that are genuinely unknown stay
 * `null` so the cards render "—" rather than a confident zero.
 */

const num = (v: unknown): number | undefined =>
  typeof v === "number" && Number.isFinite(v) ? v : undefined;

const asRecord = (v: unknown): Record<string, unknown> =>
  v && typeof v === "object" ? (v as Record<string, unknown>) : {};

const asArray = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);

/**
 * The one service family this product owns.
 *
 * NL2SQL rows carry `nodes_used` — graph nodes (`router`, `sql_gen`, …), not
 * service families. Mapping those onto `services_used` would put node names in
 * the service chips and in the service filter, where the dashboard means
 * something else by them. Every query in this product is an NL2SQL query, so the
 * honest value is the constant; the nodes are already shown, as nodes, in the
 * per-node breakdown and the expanded row's trace.
 */
const NL2SQL_SERVICES = ["nl2sql"] as const;

function toScorecardNode(raw: unknown): ScorecardNode {
  const n = asRecord(raw);
  return {
    node_name: String(n.node_name ?? ""),
    model: (n.model as string | null) ?? null,
    provider: (n.provider as string | null) ?? null,
    queries: num(n.queries),
    total_calls: num(n.total_calls),
    errors: num(n.errors),
    avg_latency_ms: num(n.avg_latency_ms),
    p50_latency_ms: num(n.p50_latency_ms),
    p95_latency_ms: num(n.p95_latency_ms),
    avg_latency_s: num(n.avg_latency_s),
    p50_latency_s: num(n.p50_latency_s),
    p95_latency_s: num(n.p95_latency_s),
    total_tokens: num(n.total_tokens),
    input_tokens: num(n.input_tokens),
    output_tokens: num(n.output_tokens),
    total_cost: num(n.total_cost),
  };
}

export function adaptScorecard(raw: unknown): Scorecard {
  const r = asRecord(raw);
  const usage = asRecord(r.usage);
  const quality = asRecord(r.quality);
  const perf = asRecord(r.perf);
  const cost = asRecord(r.cost);
  const feedback = r.quality ? asRecord(quality.feedback) : null;

  return {
    agent_id: String(r.agent_id ?? ""),
    // NL2SQL's scorecard doesn't echo the agent's display name; the page only
    // uses it as a heading fallback, which this product doesn't render.
    name: null,
    period: String(r.period ?? ""),
    since: String(r.since ?? ""),
    until: String(r.until ?? ""),
    // Not on this payload — `trends.comparison.previous_since` carries it, and
    // the view passes that to the toolbar instead.
    previous_since: "",
    usage: {
      total_queries: num(usage.total_queries) ?? 0,
      unique_users: num(usage.unique_users) ?? null,
      widget_queries: num(usage.widget_queries) ?? 0,
      per_day: asArray(usage.per_day).map((d) => {
        const row = asRecord(d);
        return {
          // `bucket` is an ISO timestamp, `day` the date — the charts key off
          // `day`, and fall back to the bucket when the granularity is hourly.
          day: String(row.day ?? row.bucket ?? ""),
          queries: num(row.queries) ?? 0,
        };
      }),
    },
    quality: {
      answered: num(quality.answered) ?? 0,
      unanswered: num(quality.unanswered) ?? 0,
      success_rate: num(quality.success_rate) ?? 0,
      failed_api_requests: num(quality.failed_api_requests) ?? 0,
      no_answer: num(quality.no_answer) ?? 0,
      // NL2SQL enforces no per-query token budget, so this is 0 rather than
      // unknown — the card is accurate, not merely filled.
      budget_exhausted: 0,
      feedback: feedback
        ? {
            positive: num(feedback.positive) ?? 0,
            negative: num(feedback.negative) ?? 0,
            total: num(feedback.total) ?? 0,
          }
        : null,
    },
    perf: {
      avg_ms: num(perf.avg_ms) ?? 0,
      p50_ms: num(perf.p50_ms) ?? 0,
      p95_ms: num(perf.p95_ms) ?? 0,
      by_node: asArray(perf.by_node).map(toScorecardNode),
      slowest: asArray(perf.slowest).map((s) => {
        const q = asRecord(s);
        return {
          chat_id: String(q.chat_id ?? ""),
          query: String(q.query ?? ""),
          latency_ms: num(q.latency_ms) ?? 0,
          total_tokens: num(q.total_tokens) ?? 0,
          trace_id: String(q.trace_id ?? ""),
        };
      }),
    },
    cost: {
      total_cost: num(cost.total_cost) ?? 0,
      avg_cost_per_query: num(cost.avg_cost_per_query) ?? 0,
      total_tokens: num(cost.total_tokens) ?? 0,
      input_tokens: num(cost.input_tokens) ?? 0,
      output_tokens: num(cost.output_tokens) ?? 0,
      // Default false, not true: an absent flag must not claim every query is
      // priced, or unpriced spend silently reads as $0.
      cost_complete: cost.cost_complete === true,
      by_model: asArray(cost.by_model).map((m) => {
        const row = asRecord(m);
        return {
          provider: String(row.provider ?? ""),
          model: String(row.model ?? ""),
          queries: num(row.queries) ?? 0,
          cost: num(row.cost) ?? 0,
        };
      }),
      by_node: asArray(cost.by_node).map(toScorecardNode),
      most_expensive: asArray(cost.most_expensive).map((m) => {
        const row = asRecord(m);
        return {
          chat_id: String(row.chat_id ?? ""),
          query: String(row.query ?? ""),
          total_tokens: num(row.total_tokens) ?? 0,
          cost_usd: num(row.cost_usd) ?? 0,
          trace_id: String(row.trace_id ?? ""),
        };
      }),
    },
    // `trend` is deliberately omitted. The page fetches a second scorecard for
    // the preceding window and derives every delta client-side, which covers
    // more metrics than this field ever did.
  };
}

export function adaptTrends(raw: unknown): TrendsResponse {
  const r = asRecord(raw);
  const series = asArray(r.series).map((s) => {
    const row = asRecord(s);
    const point: TrendsResponse["series"][number] = {
      bucket: String(row.bucket ?? ""),
      trusted: row.trusted !== false,
      total_queries: num(row.total_queries) ?? 0,
    };
    for (const metric of [
      "success_rate",
      "avg_ms",
      "p95_ms",
      "cost",
      "failures",
    ] as const) {
      const value = num(row[metric]);
      if (value !== undefined) point[metric] = value;
    }
    return point;
  });

  const regression = asRecord(r.regression);
  return {
    agent_id: String(r.agent_id ?? ""),
    bucket: (r.bucket as TrendsResponse["bucket"]) ?? "day",
    buckets: num(r.buckets) ?? series.length,
    // Not echoed by this service; the series' own bounds are what the charts
    // label their axes from.
    since: series[0]?.bucket ?? "",
    until: series[series.length - 1]?.bucket ?? "",
    metrics: ["success_rate", "avg_ms", "p95_ms", "cost", "failures"],
    series,
    regression: {
      detected: regression.detected === true,
      metric: regression.metric as string | undefined,
      from_bucket: regression.from_bucket as string | undefined,
      to_bucket: regression.to_bucket as string | undefined,
      delta: num(regression.delta),
      note: regression.note as string | undefined,
    },
  };
}

/** Days in each rolling preset, per the doc: week = 7 days, month = 30. */
const PRESET_DAYS: Record<string, number> = { week: 7, month: 30 };

/**
 * The window params `/analytics/trends` takes.
 *
 * It is the one route that does **not** accept `period`: its window is
 * `bucket` length × `weeks`, so a 7-day view is `bucket=day&weeks=7` and a
 * 30-day view is `bucket=day&weeks=30`. Sending `period` instead would either
 * 422 — every analytics param is whitelisted server-side — or fall through to
 * the `weeks=8` default and quietly plot 8 days under a toolbar that says 30.
 * A custom range still goes as `start_date`/`end_date`, which this route does
 * accept.
 */
export function trendsWindowParams(
  window: AnalyticsWindow,
): Record<string, unknown> {
  if (window.mode === "custom") {
    return { start_date: window.start, end_date: window.end };
  }
  return { bucket: "day", weeks: PRESET_DAYS[window.period] ?? 7 };
}

function toNodeDatum(raw: unknown): NodeDatum {
  const n = asRecord(raw);
  return {
    node_name: String(n.node_name ?? ""),
    provider: (n.provider as string | null) ?? null,
    model: (n.model as string | null) ?? null,
    calls: num(n.calls) ?? num(n.total_calls),
    input_tokens: num(n.input_tokens) ?? 0,
    output_tokens: num(n.output_tokens) ?? 0,
    total_tokens: num(n.total_tokens) ?? 0,
    // The service prices a node whole; it does not split spend by direction.
    input_cost: num(n.input_cost) ?? 0,
    output_cost: num(n.output_cost) ?? 0,
    total_cost: num(n.total_cost) ?? 0,
    // `avg_latency_ms` is this node's per-call mean for the query, which is what
    // the breakdown's latency fallback wants.
    latency_ms: num(n.latency_ms) ?? num(n.avg_latency_ms),
    total_latency_ms: num(n.total_latency_ms),
  };
}

/**
 * Our-end timings NL2SQL measures per query, as `service_calls`.
 *
 * Only `sql_exec_ms` becomes one: `sql_exec` is a real graph node (it appears in
 * `failed_stage`), so the number is directly attributable and is a truer latency
 * for it than the LangSmith run time in `node_data`, which `deriveNodeStats`
 * prefers accordingly. `db_fetch_ms` is schema retrieval, not a node, so it is
 * left out rather than attributed to a node that did not spend it.
 */
function toServiceCalls(
  metrics: Record<string, unknown>,
): ServiceCall[] | null {
  const sqlExecMs = num(metrics.sql_exec_ms);
  if (sqlExecMs === undefined) return null;
  return [{ node_name: "sql_exec", latency_ms: sqlExecMs }];
}

function toQueryRow(raw: unknown): QueryRow {
  const r = asRecord(raw);
  const m = asRecord(r.metrics);
  const nodeData = asArray(m.node_data).map(toNodeDatum);

  return {
    chat_id: String(r.chat_id ?? ""),
    session_id: (r.session_id as string | null) ?? null,
    user_id: (r.user_id as string | null) ?? null,
    timestamp: String(r.timestamp ?? ""),
    query: String(r.query ?? ""),
    refined_query: (r.refined_query as string | null) ?? null,
    route: (r.route as string | null) ?? null,
    services_used: [...NL2SQL_SERVICES],
    status: String(r.status ?? ""),
    outcome: String(r.outcome ?? ""),
    is_answered: r.is_answered === true,
    // No stop reason or confidence is recorded per query on this service.
    stop_reason: null,
    confidence: null,
    failure_category: (r.failure_category as string | null) ?? null,
    failed_stage: (r.failed_stage as string | null) ?? null,
    failure_detail: (r.failure_detail as string | null) ?? null,
    provider: (r.provider as string | null) ?? null,
    // Documented as the answer model only; the real per-model split is in
    // node_data, which the breakdown reads.
    model: (r.model as string | null) ?? null,
    // Per-query widget provenance isn't on the row (only the window's
    // `usage.widget_queries` total), so this cannot be claimed either way.
    from_widget: false,
    key_type: (r.key_type as string | null) ?? null,
    feedback: (r.feedback as QueryRow["feedback"]) ?? null,
    trace_id: (r.trace_id as string | null) ?? null,
    metrics: {
      latency_ms: num(m.latency_ms) ?? 0,
      input_tokens: num(m.input_tokens) ?? 0,
      output_tokens: num(m.output_tokens) ?? 0,
      total_tokens: num(m.total_tokens) ?? 0,
      cost_usd: num(m.cost_usd) ?? 0,
      cost_complete: m.cost_complete === true,
      retry_count: num(m.retry_count) ?? 0,
      node_data: nodeData.length ? nodeData : null,
      service_calls: toServiceCalls(m),
    },
  };
}

export function adaptQueryLog(raw: unknown): QueryLogResponse {
  const r = asRecord(raw);
  const queries = asArray(r.queries).map(toQueryRow);
  return {
    agent_id: String(r.agent_id ?? ""),
    period: String(r.period ?? ""),
    sort: String(r.sort ?? ""),
    order: String(r.order ?? ""),
    total_matching: num(r.total_matching) ?? queries.length,
    limit: num(r.limit) ?? queries.length,
    offset: num(r.offset) ?? 0,
    returned: num(r.returned) ?? queries.length,
    queries,
  };
}
