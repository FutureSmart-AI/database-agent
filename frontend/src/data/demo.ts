"use client";

import { useQuery } from "@tanstack/react-query";

import axios from "@/platform/utils/axios";

import { APIS } from "./api";

/**
 * Free questions on the shared sample-data agents.
 *
 * A sample-data agent runs on FutureSmart's model key, so anyone signed in can
 * ask it questions without a key or a database of their own. Each person gets a
 * few a day and a fixed number in total; the service counts them and refuses
 * the next one with a 429 that says why. This is the same count, for showing
 * before that happens.
 *
 * Accounts with a verified aidemos.com or futuresmart.ai email are `internal`:
 * no limits (`unlimited`), and the limit and remaining fields are null.
 */
export interface DemoAllowance {
  audience?: "public" | "internal";
  unlimited?: boolean;
  daily_limit: number | null;
  daily_used: number;
  daily_remaining: number | null;
  /** When today's allowance next frees up (ISO, UTC), once it is used up. */
  daily_resets_at: string | null;
  total_limit: number | null;
  total_used: number;
  total_remaining: number | null;
  /** False when free questions are paused for everyone this month. */
  budget_open: boolean;
}

/** The public repository, for running Database Agent yourself. */
export const SELF_HOST_URL = "https://github.com/FutureSmart-AI/database-agent";

export async function fetchDemoAllowance(): Promise<DemoAllowance> {
  const response = await axios.get<DemoAllowance>(APIS.DEMO_ALLOWANCE);
  return response.data;
}

export const DEMO_ALLOWANCE_KEY = ["demoAllowance"] as const;

/** Only fetched where a sample-data agent is on screen. */
export function useDemoAllowance(enabled: boolean) {
  return useQuery({
    queryKey: DEMO_ALLOWANCE_KEY,
    queryFn: fetchDemoAllowance,
    enabled,
    staleTime: 30 * 1000,
  });
}

/** Whether no free question can be asked right now, and the sentence saying why. */
export function demoBlocked(allowance?: DemoAllowance): string | null {
  if (!allowance || allowance.unlimited) return null;
  if ((allowance.total_remaining ?? 0) <= 0) {
    return `You have used all ${allowance.total_limit} free sample-data questions.`;
  }
  if ((allowance.daily_remaining ?? 0) <= 0) {
    const when = allowance.daily_resets_at
      ? new Date(allowance.daily_resets_at).toLocaleString(undefined, {
          dateStyle: "medium",
          timeStyle: "short",
        })
      : null;
    return `You have used today's ${allowance.daily_limit} free questions${
      when ? `; more are available from ${when}` : ""
    }.`;
  }
  if (!allowance.budget_open) {
    return "Free sample-data questions are paused for the rest of this month.";
  }
  return null;
}
