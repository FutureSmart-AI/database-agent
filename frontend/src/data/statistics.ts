"use client";

import { useQuery } from "@tanstack/react-query";

import { buildApiUrl } from "@/platform/utils";
import axios from "@/platform/utils/axios";

import { APIS } from "./api";

/**
 * Agent statistics, from `GET /nl2sql/api/v1/agents/{agent_id}/statistics`.
 *
 * All-time totals — requests, tokens and the two halves of a question's latency
 * — with no date window: the route takes `start_time`/`end_time` but answers
 * **200** with `{"message":"Error in get_bot_statistics","status":false}` when
 * they are sent.
 *
 * No longer what Analytics reads. That page now uses the NL2SQL service's
 * `/analytics/*` routes, which are windowed and cover outcome, cost and
 * per-node data this one never had. Kept because it is the only all-time
 * lifetime figure the service offers, and it is a working binding for it.
 *
 * Latencies come back in **seconds**; requests and tokens are counts.
 */

interface WireStatistics {
  total_requests?: number;
  avg_gpt_response_time?: number | null;
  avg_db_fetch_time?: number | null;
  total_tokens_consumed?: number | null;
  user_request_counts?: Array<{
    user_id?: string | null;
    request_count?: number;
  }>;
  bot_request_counts?: Array<{
    agent_id?: string;
    bot_request_count?: number;
  }>;
  /** Set when the service reports a failure inside a 200 response. */
  status?: boolean;
  message?: string;
}

/**
 * `null` means the service recorded nothing for that metric, which is not the
 * same as a measured zero — an agent asked 56 questions comes back with
 * `total_tokens_consumed: 0` and another with `null`. Collapsing both to 0 (as
 * this did) printed "0 tokens" over questions that certainly spent some, so the
 * nullability is carried through and the cards render "—" for it.
 */
export interface AgentStatistics {
  requests: number;
  tokens: number | null;
  /** Milliseconds, converted from the service's seconds. */
  model_ms: number | null;
  db_ms: number | null;
  users: Array<{ user: string | null; requests: number }>;
}

/**
 * Every question this agent has answered — no date window.
 *
 * The route takes `start_time`/`end_time`, but sending them answers **200** with
 * `{"message":"Error in get_bot_statistics","status":false}` and no numbers, so a
 * period selector here would only ever zero the page. Reported to the backend;
 * once it works this becomes a windowed read and the view gains the selector.
 */
export function useAgentStatistics(serviceId: string | null | undefined) {
  return useQuery({
    queryKey: ["statistics", serviceId],
    enabled: Boolean(serviceId),
    refetchOnWindowFocus: false,
    queryFn: async (): Promise<AgentStatistics> => {
      const url = buildApiUrl(APIS.NL2SQL_STATISTICS, {
        service_id: serviceId as string,
      });
      const response = await axios.get<
        { data?: WireStatistics } & WireStatistics
      >(url);
      const row = response.data.data ?? response.data;

      // A failure reported inside a 200 must not render as a page of zeros.
      if (row.status === false || row.total_requests === undefined) {
        throw new Error(row.message ?? "The service returned no statistics.");
      }

      const seconds = (value?: number | null) =>
        value == null ? null : value * 1000;

      return {
        requests: row.total_requests ?? 0,
        tokens: row.total_tokens_consumed ?? null,
        model_ms: seconds(row.avg_gpt_response_time),
        db_ms: seconds(row.avg_db_fetch_time),
        users: (row.user_request_counts ?? []).map((entry) => ({
          user: entry.user_id ?? null,
          requests: entry.request_count ?? 0,
        })),
      };
    },
  });
}
