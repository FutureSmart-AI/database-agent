"use client";

import { type UseQueryResult } from "@tanstack/react-query";

import { useAnalyticsQuery } from "@/platform/analytics/hooks/useAnalyticsQuery";
import type { AnalyticsWindow } from "@/platform/analytics/types";

import { APIS } from "./api";

/**
 * Why queries failed, from `GET …/analytics/failures`.
 *
 * The one analytics route with no agent-dashboard equivalent, so it is fetched
 * here rather than through the shared scope's endpoint map — nothing on the
 * dashboard would ever call it.
 */

/** Whose problem a category is, for the badge beside it. */
export type FailureOwner =
  | "model"
  | "operator"
  | "schema"
  | "infrastructure"
  | "question"
  | "us"
  | "unknown";

/**
 * The documented vocabulary. A category the service adds later still renders —
 * it just falls through to "unknown" instead of being dropped.
 */
export const FAILURE_CATEGORIES: Record<
  string,
  { label: string; means: string; owner: FailureOwner }
> = {
  sql_error: {
    label: "SQL error",
    means: "The database rejected the generated SQL",
    owner: "model",
  },
  db_connection: {
    label: "DB connection",
    means: "Couldn't reach the database at all",
    owner: "operator",
  },
  no_rows: {
    label: "No rows",
    means: "SQL ran fine, returned nothing",
    owner: "schema",
  },
  sql_generation: {
    label: "SQL generation",
    means: "No SQL was produced",
    owner: "model",
  },
  llm_error: {
    label: "LLM error",
    means: "A node errored — provider outage, rate limit",
    owner: "infrastructure",
  },
  out_of_scope: {
    label: "Out of scope",
    means: "Router answered directly, answer unusable",
    owner: "question",
  },
  unanswered: {
    label: "Unanswered",
    means: "Rows came back, answer step couldn't use them",
    owner: "model",
  },
  exception: {
    label: "Exception",
    means: "The request raised",
    owner: "us",
  },
};

export interface FailureCategoryRow {
  failure_category: string;
  count: number;
  pct: number;
}

export interface FailureStageRow {
  failed_stage: string;
  count: number;
}

export interface FailedQueryRow {
  query_norm: string;
  failure_category: string | null;
  failed_stage: string | null;
  occurrences: number;
  first_seen: string | null;
  last_seen: string | null;
  sample_failure_detail: string | null;
}

export interface FailuresResponse {
  total_failures: number;
  by_category: FailureCategoryRow[];
  by_stage: FailureStageRow[];
  top_failed_queries: FailedQueryRow[];
}

export function useFailures(
  agentId: string | null | undefined,
  window: AnalyticsWindow,
  opts: {
    category?: string;
    failed_stage?: string;
    limit?: number;
    offset?: number;
  } = {},
): UseQueryResult<FailuresResponse> {
  const { category, failed_stage, limit = 50, offset = 0 } = opts;
  return useAnalyticsQuery<FailuresResponse>({
    resource: "failures",
    endpoint: APIS.ANALYTICS_FAILURES,
    agentId,
    window,
    params: {
      ...(category && { category }),
      ...(failed_stage && { failed_stage }),
      limit,
      offset,
    },
    keyExtra: [category ?? "", failed_stage ?? "", limit, offset],
    // Nothing recorded is nothing failing — the best possible reading of this
    // tab, and the state every agent predating analytics is in. Reporting it as
    // a load failure asks the reader to retry a 404 that will not change.
    emptyOn404: () => ({
      total_failures: 0,
      by_category: [],
      by_stage: [],
      top_failed_queries: [],
    }),
  });
}
