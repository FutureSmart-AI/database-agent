import { describe, expect, it } from "vitest";

import {
  adaptQueryLog,
  adaptScorecard,
  adaptTrends,
  trendsWindowParams,
} from "../analyticsAdapters";

/**
 * Payloads copied from `analytics-api-for-ui.md` (2026-08-14), whose bodies were
 * captured from live calls rather than written from the spec. If the service
 * changes shape, these are what should fail first.
 */

const SCORECARD = {
  agent_id: "NL2SQL_7C4A91E2",
  period: "week",
  since: "2026-08-07T16:12:26Z",
  until: "2026-08-14T16:12:26Z",
  usage: {
    total_queries: 73,
    unique_users: 5,
    widget_queries: 13,
    bucket: "day",
    per_day: [
      { bucket: "2026-08-07T00:00:00Z", day: "2026-08-07", queries: 13 },
    ],
  },
  quality: {
    answered: 61,
    unanswered: 12,
    success_rate: 83.6,
    failed_api_requests: 0,
    no_answer: 12,
    feedback: { positive: 16, negative: 6, total: 22 },
  },
  perf: {
    avg_ms: 6495,
    p50_ms: 6919,
    p95_ms: 10045,
    by_node: [
      {
        node_name: "final_answer",
        model: "gemini-3.1-flash-lite",
        provider: "google",
        queries: 56,
        total_calls: 56,
        errors: 0,
        avg_latency_ms: 2545,
        p50_latency_ms: 2592,
        p95_latency_ms: 3275,
        avg_latency_s: 2.54,
        p95_latency_s: 3.27,
        total_tokens: 204323,
        input_tokens: 184123,
        output_tokens: 20170,
        total_cost: 0.07782,
      },
    ],
    slowest: [
      {
        chat_id: "c1",
        query: "slow one",
        latency_ms: 12345,
        total_tokens: 12150,
        trace_id: "t1",
      },
    ],
  },
  cost: {
    total_cost: 0.185843,
    avg_cost_per_query: 0.002546,
    total_tokens: 529338,
    input_tokens: 490880,
    output_tokens: 38458,
    cost_complete: false,
    by_model: [
      {
        provider: "google",
        model: "gemini-3.1-flash-lite",
        queries: 73,
        cost: 0.185843,
      },
    ],
    most_expensive: [
      {
        chat_id: "c2",
        query: "pricey one",
        total_tokens: 12150,
        cost_usd: 0.006089,
      },
    ],
  },
};

describe("adaptScorecard", () => {
  it("carries every metric the dashboard cards read", () => {
    const sc = adaptScorecard(SCORECARD);
    expect(sc.usage.total_queries).toBe(73);
    expect(sc.usage.unique_users).toBe(5);
    expect(sc.quality.success_rate).toBe(83.6);
    expect(sc.quality.feedback).toEqual({
      positive: 16,
      negative: 6,
      total: 22,
    });
    expect(sc.perf.p95_ms).toBe(10045);
    expect(sc.cost.total_cost).toBeCloseTo(0.185843);
    expect(sc.cost.by_model[0].model).toBe("gemini-3.1-flash-lite");
  });

  it("keys the volume chart off `day`, which the charts plot", () => {
    expect(adaptScorecard(SCORECARD).usage.per_day).toEqual([
      { day: "2026-08-07", queries: 13 },
    ]);
  });

  // An hourly bucket has no `day`; the ISO bucket is the only label there is.
  it("falls back to the ISO bucket when the granularity is hourly", () => {
    const hourly = {
      ...SCORECARD,
      usage: {
        ...SCORECARD.usage,
        bucket: "hour",
        per_day: [{ bucket: "2026-08-07T09:00:00Z", queries: 4 }],
      },
    };
    expect(adaptScorecard(hourly).usage.per_day).toEqual([
      { day: "2026-08-07T09:00:00Z", queries: 4 },
    ]);
  });

  it("fills the fields NL2SQL does not send, without inventing a measurement", () => {
    const sc = adaptScorecard(SCORECARD);
    expect(sc.name).toBeNull();
    expect(sc.previous_since).toBe("");
    // No per-query token budget exists on this service, so 0 is the truth.
    expect(sc.quality.budget_exhausted).toBe(0);
    // Deltas are derived from a second scorecard, not from this field.
    expect(sc.trend).toBeUndefined();
  });

  // Rendering unpriced spend as a complete total is the one failure the doc
  // calls out by name.
  it("never claims costs are complete when the flag is absent", () => {
    const noFlag = { ...SCORECARD, cost: { ...SCORECARD.cost } };
    delete (noFlag.cost as Record<string, unknown>).cost_complete;
    expect(adaptScorecard(noFlag).cost.cost_complete).toBe(false);
    expect(adaptScorecard(SCORECARD).cost.cost_complete).toBe(false);
  });

  it("survives a 200 with nothing in it", () => {
    const sc = adaptScorecard({});
    expect(sc.usage.total_queries).toBe(0);
    expect(sc.perf.slowest).toEqual([]);
    expect(sc.cost.by_model).toEqual([]);
    expect(sc.quality.feedback).toBeNull();
  });
});

const TRENDS = {
  bucket: "day",
  buckets: 8,
  series: [
    {
      bucket: "2026-08-07T00:00:00Z",
      trusted: true,
      total_queries: 13,
      success_rate: 84.6,
      avg_ms: 6183,
      p95_ms: 8500,
      cost: 0.031796,
      failures: 2,
    },
    {
      bucket: "2026-08-08T00:00:00Z",
      trusted: true,
      total_queries: 9,
      success_rate: 77.8,
      avg_ms: 7010,
      p95_ms: 9100,
      cost: 0.0221,
      failures: 2,
    },
  ],
  comparison: {
    previous_since: "2026-07-31T16:12:26Z",
    total_queries: { current: 73, previous: 71, delta: 2, pct_change: 2.8 },
  },
  regression: { detected: false },
};

describe("adaptTrends", () => {
  it("keeps every plotted metric on each point", () => {
    const t = adaptTrends(TRENDS);
    expect(t.series).toHaveLength(2);
    expect(t.series[0]).toMatchObject({
      bucket: "2026-08-07T00:00:00Z",
      trusted: true,
      total_queries: 13,
      success_rate: 84.6,
      avg_ms: 6183,
      cost: 0.031796,
      failures: 2,
    });
  });

  it("derives the window bounds the charts label axes from", () => {
    const t = adaptTrends(TRENDS);
    expect(t.since).toBe("2026-08-07T00:00:00Z");
    expect(t.until).toBe("2026-08-08T00:00:00Z");
    expect(t.bucket).toBe("day");
  });

  it("treats a missing regression flag as no regression", () => {
    expect(adaptTrends({ series: [] }).regression.detected).toBe(false);
  });
});

/**
 * `/analytics/trends` is the one route that takes no `period`. Its window is
 * `bucket` length × `weeks`, and every param is whitelisted server-side — so
 * sending `period` either 422s or falls through to the `weeks=8` default and
 * plots 8 days under a toolbar claiming 30.
 */
describe("trendsWindowParams", () => {
  it("turns the 7-day preset into 7 daily buckets, not a period", () => {
    const p = trendsWindowParams({ mode: "preset", period: "week" });
    expect(p).toEqual({ bucket: "day", weeks: 7 });
    expect(p).not.toHaveProperty("period");
  });

  it("turns the 30-day preset into 30 daily buckets", () => {
    expect(trendsWindowParams({ mode: "preset", period: "month" })).toEqual({
      bucket: "day",
      weeks: 30,
    });
  });

  it("passes a custom range straight through, which this route does accept", () => {
    expect(
      trendsWindowParams({
        mode: "custom",
        start: "2026-08-01",
        end: "2026-08-14",
      }),
    ).toEqual({ start_date: "2026-08-01", end_date: "2026-08-14" });
  });
});

const QUERY_LOG = {
  total_matching: 73,
  limit: 20,
  offset: 0,
  returned: 1,
  queries: [
    {
      chat_id: "chat-1",
      session_id: "sess-1",
      user_id: "lead@acme.io",
      timestamp: "2026-08-14T06:22:15Z",
      query: "best selling category by units",
      refined_query: "…",
      route: "sql",
      nodes_used: [
        "router",
        "db_router",
        "sql_gen",
        "sql_exec",
        "final_answer",
      ],
      db_id: "DB_3E88B07D",
      cross_db: false,
      sql_query: "SELECT 1",
      selected_tables: ["orders", "customers"],
      rows_returned: 50,
      status: "answered",
      outcome: "success",
      is_answered: true,
      failure_category: null,
      failed_stage: null,
      feedback: "positive",
      trace_id: "tr-1",
      metrics: {
        latency_ms: 6333,
        db_fetch_ms: 38,
        sql_exec_ms: 806,
        input_tokens: 6732,
        output_tokens: 568,
        total_tokens: 7300,
        cost_usd: 0.002552,
        cost_complete: true,
        retry_count: 0,
        node_data: [
          {
            node_name: "final_answer",
            provider: "google",
            model: "gemini-3.1-flash-lite",
            total_calls: 1,
            input_tokens: 6000,
            output_tokens: 500,
            total_tokens: 6500,
            total_cost: 0.0021,
            avg_latency_ms: 2545,
          },
        ],
      },
    },
  ],
};

describe("adaptQueryLog", () => {
  it("carries the row fields the log table renders", () => {
    const row = adaptQueryLog(QUERY_LOG).queries[0];
    expect(row.chat_id).toBe("chat-1");
    expect(row.user_id).toBe("lead@acme.io");
    expect(row.route).toBe("sql");
    expect(row.is_answered).toBe(true);
    expect(row.feedback).toBe("positive");
    expect(row.metrics.latency_ms).toBe(6333);
    expect(row.metrics.total_tokens).toBe(7300);
  });

  it("keeps paging fields so the table's total and pager agree", () => {
    const res = adaptQueryLog(QUERY_LOG);
    expect(res.total_matching).toBe(73);
    expect(res.limit).toBe(20);
    expect(res.offset).toBe(0);
  });

  // `nodes_used` is graph nodes, not service families — putting those in the
  // service chips would mean something else entirely on the shared components.
  it("reports the one service this product owns, not the graph nodes", () => {
    expect(adaptQueryLog(QUERY_LOG).queries[0].services_used).toEqual([
      "nl2sql",
    ]);
  });

  it("maps node latency and cost so the per-node breakdown populates", () => {
    const node = adaptQueryLog(QUERY_LOG).queries[0].metrics.node_data?.[0];
    expect(node?.node_name).toBe("final_answer");
    expect(node?.calls).toBe(1);
    expect(node?.latency_ms).toBe(2545);
    expect(node?.total_cost).toBeCloseTo(0.0021);
    // The service prices a node whole; it does not split spend by direction.
    expect(node?.input_cost).toBe(0);
  });

  it("turns the measured sql_exec time into a service call", () => {
    expect(adaptQueryLog(QUERY_LOG).queries[0].metrics.service_calls).toEqual([
      { node_name: "sql_exec", latency_ms: 806 },
    ]);
  });

  it("omits service calls when nothing measured one", () => {
    const noTiming = {
      ...QUERY_LOG,
      queries: [
        {
          ...QUERY_LOG.queries[0],
          metrics: { ...QUERY_LOG.queries[0].metrics, sql_exec_ms: undefined },
        },
      ],
    };
    expect(adaptQueryLog(noTiming).queries[0].metrics.service_calls).toBeNull();
  });

  it("survives an empty page", () => {
    const res = adaptQueryLog({ queries: [] });
    expect(res.queries).toEqual([]);
    expect(res.total_matching).toBe(0);
  });
});
