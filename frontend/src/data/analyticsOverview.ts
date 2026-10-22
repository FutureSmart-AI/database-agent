"use client";

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import {
  windowKey,
  windowToRequestParams,
} from "@/platform/analytics/constants";
import type { AnalyticsWindow } from "@/platform/analytics/types";
import { getHttpStatus } from "@/platform/analytics/utils";
import axios from "@/platform/utils/axios";

import { APIS } from "./api";

/**
 * Every agent's analytics in one grid, from `GET /v1/agents/analytics/overview`.
 *
 * The only analytics route that is not per-agent, and the one this product
 * never called: Analytics opened on an agent picker, so the workspace-level
 * question — which agent is failing, which is expensive — had no screen at all
 * and every answer needed six clicks and a scorecard each.
 *
 * Not routed through `useAnalyticsQuery`: that hook builds an agent-scoped URL
 * and keys its cache by agent, neither of which applies here.
 *
 * `owner_id` is deliberately never sent. A session caller is scoped to their
 * own agents server-side; passing one asks for someone else's and is rejected
 * for anything but the master key.
 */

export interface OverviewAgentRow {
  agent_id: string;
  owner_id: string | null;
  name: string | null;
  total_queries: number;
  unique_users: number | null;
  answered: number;
  unanswered: number;
  success_rate: number | null;
  failed_api_requests: number;
  avg_ms: number | null;
  p95_ms: number | null;
  total_tokens: number;
  total_cost: number;
  avg_cost_per_query: number | null;
  cost_complete: boolean;
  top_failure_category: string | null;
}

export interface OverviewResponse {
  total_agents: number;
  summary: {
    total_queries: number;
    total_cost: number;
    /** False when some queries in the window are still unpriced. */
    cost_complete: boolean;
  };
  agents: OverviewAgentRow[];
}

/**
 * Columns the endpoint can sort on.
 *
 * Unlike the filter vocabularies, this one is not generated: the spec declares
 * `sort` as a bare string with a default and no documented values, so there is
 * nothing to extract. Declared here, next to its only use, and sent only from
 * a header the reader clicked.
 */
export const OVERVIEW_SORTS = [
  "total_queries",
  "success_rate",
  "total_cost",
  "avg_ms",
] as const;

export type OverviewSort = (typeof OVERVIEW_SORTS)[number];

const EMPTY: OverviewResponse = {
  total_agents: 0,
  summary: { total_queries: 0, total_cost: 0, cost_complete: true },
  agents: [],
};

export function useAnalyticsOverview(
  window: AnalyticsWindow,
  opts: {
    sort?: OverviewSort;
    order?: "asc" | "desc";
    /** Server-side search over agent ids. */
    q?: string;
    limit?: number;
    offset?: number;
  } = {},
): UseQueryResult<OverviewResponse> {
  const { sort, order = "desc", q, limit, offset = 0 } = opts;
  return useQuery<OverviewResponse>({
    queryKey: [
      "analytics",
      "overview",
      windowKey(window),
      sort ?? "",
      order,
      q ?? "",
      limit ?? 0,
      offset,
    ],
    // None of these change on a retry: 404 is "nothing recorded yet", 401/403
    // is the wrong credentials, 422 a parameter this build will keep sending.
    retry: (failureCount, error) => {
      const status = getHttpStatus(error);
      if (status && status >= 400 && status < 500) return false;
      return failureCount < 2;
    },
    queryFn: async () => {
      try {
        const res = await axios.get(APIS.ANALYTICS_OVERVIEW, {
          params: {
            ...windowToRequestParams(window),
            ...(sort ? { sort } : {}),
            ...(sort ? { order } : {}),
            ...(q ? { q } : {}),
            ...(limit ? { limit } : {}),
            ...(offset ? { offset } : {}),
          },
        });
        return res.data as OverviewResponse;
      } catch (error) {
        // A workspace whose agents have never been asked anything is empty,
        // not broken — analytics records nothing retroactively.
        if (getHttpStatus(error) === 404) return EMPTY;
        throw error;
      }
    },
  });
}
