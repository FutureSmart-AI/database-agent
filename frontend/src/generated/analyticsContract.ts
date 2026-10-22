/**
 * GENERATED FILE — do not edit.
 *
 * The analytics query parameters the NL2SQL service accepts, extracted from its
 * OpenAPI document (spec version 0.1.0) by
 * `scripts/gen-analytics-contract.ts`. Regenerate with:
 *
 *   bun run gen:analytics
 *
 * `values` is the closed set a parameter accepts, or `null` where the spec
 * documents no vocabulary — `sort`, `order` and `period` have none, so those
 * stay declared alongside the code that uses them.
 */
import type { AnalyticsContract } from "../lib/openapiVocab";

export const ANALYTICS_CONTRACT = {
  failures: {
    category: {
      default: null,
      min: null,
      max: null,
      values: [
        "sql_error",
        "db_connection",
        "no_rows",
        "sql_generation",
        "out_of_scope",
        "unanswered",
        "exception",
      ],
    },
    end_date: { default: null, min: null, max: null, values: null },
    failed_stage: {
      default: null,
      min: null,
      max: null,
      values: [
        "router",
        "db_router",
        "sql_gen",
        "sql_exec",
        "final_answer",
        "chat_api",
      ],
    },
    limit: { default: 50, min: 1, max: 200, values: null },
    offset: { default: 0, min: 0, max: null, values: null },
    period: { default: "week", min: null, max: null, values: null },
    start_date: { default: null, min: null, max: null, values: null },
  },
  overview: {
    end_date: { default: null, min: null, max: null, values: null },
    limit: { default: 50, min: 1, max: 200, values: null },
    offset: { default: 0, min: 0, max: null, values: null },
    order: { default: "desc", min: null, max: null, values: null },
    owner_id: { default: null, min: null, max: null, values: null },
    period: { default: "week", min: null, max: null, values: null },
    q: { default: null, min: null, max: null, values: null },
    sort: { default: "total_queries", min: null, max: null, values: null },
    start_date: { default: null, min: null, max: null, values: null },
  },
  queries: {
    chat_id: { default: null, min: null, max: null, values: null },
    db_id: { default: null, min: null, max: null, values: null },
    end_date: { default: null, min: null, max: null, values: null },
    failed_stage: { default: null, min: null, max: null, values: null },
    failure_category: { default: null, min: null, max: null, values: null },
    feedback: {
      default: null,
      min: null,
      max: null,
      values: ["positive", "negative", "none", "any"],
    },
    include_node_data: { default: true, min: null, max: null, values: null },
    limit: { default: 20, min: 1, max: 100, values: null },
    min_cost_usd: { default: null, min: 0, max: null, values: null },
    min_latency_ms: { default: null, min: 0, max: null, values: null },
    min_tokens: { default: null, min: 0, max: null, values: null },
    model: { default: null, min: null, max: null, values: null },
    offset: { default: 0, min: 0, max: null, values: null },
    order: { default: "desc", min: null, max: null, values: null },
    outcome: {
      default: null,
      min: null,
      max: null,
      values: ["success", "failure"],
    },
    period: { default: "week", min: null, max: null, values: null },
    route: {
      default: null,
      min: null,
      max: null,
      values: ["sql", "cross_db", "pandas", "direct_answer"],
    },
    sort: { default: "latency_ms", min: null, max: null, values: null },
    start_date: { default: null, min: null, max: null, values: null },
    status: {
      default: null,
      min: null,
      max: null,
      values: ["answered", "unanswered"],
    },
  },
  scorecard: {
    bucket: {
      default: "day",
      min: null,
      max: null,
      values: ["hour", "day", "week", "month"],
    },
    end_date: { default: null, min: null, max: null, values: null },
    period: { default: "week", min: null, max: null, values: null },
    start_date: { default: null, min: null, max: null, values: null },
    top_n: { default: 10, min: 1, max: 50, values: null },
  },
  syncCosts: {
    end_date: { default: null, min: null, max: null, values: null },
    period: { default: "week", min: null, max: null, values: null },
    start_date: { default: null, min: null, max: null, values: null },
    strategy: {
      default: "run_id",
      min: null,
      max: null,
      values: ["run_id", "metadata", "both"],
    },
  },
  trends: {
    bucket: { default: "week", min: null, max: null, values: null },
    end_date: { default: null, min: null, max: null, values: null },
    metrics: {
      default: null,
      min: null,
      max: null,
      values: [
        "success_rate",
        "avg_ms",
        "p95_ms",
        "cost",
        "failures",
        "total_queries",
      ],
    },
    start_date: { default: null, min: null, max: null, values: null },
    weeks: { default: 8, min: 1, max: 52, values: null },
  },
} as const satisfies AnalyticsContract;

export type AnalyticsEndpoint = keyof typeof ANALYTICS_CONTRACT;
