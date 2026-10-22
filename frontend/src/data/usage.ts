"use client";

import { useQuery } from "@tanstack/react-query";
import dayjs from "dayjs";

import { buildApiUrl } from "@/platform/utils";
import axios from "@/platform/utils/axios";

import { APIS } from "./api";
import { useOwnerId } from "./session";
import type { AgentUsage } from "./types";

/**
 * Everything the Usage & Limits screen reads, from the NL2SQL service:
 * `GET /v1/aggregate`, `GET /v1/trend`, `GET /v1/owners/{id}/limits` and
 * `GET /v1/events`.
 *
 * Three rules from the API contract shape this whole file, and none of them
 * are re-derived on the client:
 *
 * 1. There is no ungrouped total and no cost figure. A total is the sum of one
 *    grouping — `key_type` for "platform + own keys" — and cost is
 *    `total_tokens × token_rate_usd`, with the rate coming from `/limits`.
 *    Adding a second source for either would be a second number that can
 *    disagree with the first.
 * 2. `group_by` accepts operation, label, agent_id, key_type, model, provider
 *    and phase. Anything else — `service_type` above all — is a 422.
 * 3. `null` in a dimension is real data, not a failure: `db_query` and
 *    `code_execution` events have no model or provider.
 *
 * **`owner_id=me` does not work on the query routes.** `/v1/owners/me/limits`
 * resolves the session cookie, but `/v1/aggregate`, `/v1/trend` and `/v1/events`
 * answer `me` with an EMPTY result set rather than the caller's data — verified
 * live on 2026-08-26, where `owner_id=me` returned no groups and the same window
 * under the signed-in email returned 7,819 tokens. An empty answer is the worst
 * failure mode available: the screen reads "no usage recorded" instead of
 * "wrong owner". So the three query routes are sent the viewer's email, and
 * every one of them stays disabled until the profile has resolved rather than
 * firing an unscoped request that would look like an empty period.
 */

/** `/v1/owners/{owner_id}/limits` — the one route that does resolve `me`. */
const ME = "me";

/* ── the aggregate ──────────────────────────────────────────────────────── */

/** The dimensions `/v1/aggregate` will group by. Nothing else is accepted. */
export type UsageGroupBy =
  | "operation"
  | "label"
  | "agent_id"
  | "key_type"
  | "model"
  | "provider"
  | "phase";

/** The metrics every aggregate and trend response carries. */
export type UsageMetricName =
  | "total_tokens"
  | "input_tokens"
  | "output_tokens"
  | "execution_time_seconds"
  | "rows_returned";

export interface AggregateMetric {
  metric_name: UsageMetricName;
  total: number;
  avg: number;
  min: number;
  max: number;
  count: number;
}

/**
 * One aggregate group: its dimension values, its event count and its metrics.
 *
 * A dimension is `string | null` — a `db_query` group really does come back
 * with `model: null`, and dropping those groups would hide usage that happened.
 */
export interface AggregateGroup extends Partial<
  Record<UsageGroupBy, string | null>
> {
  event_count: number;
  metrics: AggregateMetric[];
}

export interface AggregateResponse {
  group_by: UsageGroupBy[];
  groups: AggregateGroup[];
}

/** Every filter `/v1/aggregate`, `/v1/trend` and `/v1/events` share. */
export interface UsageFilters {
  key_type?: "platform-key" | "owner-key";
  agent_id?: string;
  operation?: string;
  label?: string;
  model?: string;
  provider?: string;
  phase?: string;
}

/** Whose provider key paid for the work. `total` is both, summed. */
export type UsageSource = "total" | "platform" | "owner";

export type UsageBucket = "day" | "week" | "month";

/** The periods the screen offers, as days for `/v1/trend`. */
export const USAGE_PERIODS = [
  { value: "7d", label: "Last 7 days", days: 7 },
  { value: "30d", label: "Last 30 days", days: 30 },
  { value: "90d", label: "Last 90 days", days: 90 },
] as const;

export type UsagePeriod = (typeof USAGE_PERIODS)[number]["value"];

export const DEFAULT_USAGE_PERIOD: UsagePeriod = "30d";

export function periodDays(period: UsagePeriod): number {
  return (
    USAGE_PERIODS.find((entry) => entry.value === period)?.days ??
    USAGE_PERIODS[1].days
  );
}

export function periodLabel(period: UsagePeriod): string {
  return USAGE_PERIODS.find((entry) => entry.value === period)?.label ?? period;
}

/**
 * The window a period covers, ending now.
 *
 * `/v1/trend` takes `days` and works this out itself; `/v1/aggregate` takes
 * dates, so the two must be asked for the same window or the trend and the
 * cards above it describe different periods.
 */
export function usageWindow(period: UsagePeriod = DEFAULT_USAGE_PERIOD) {
  const end = dayjs();
  return {
    start_date: end.subtract(periodDays(period), "day").toISOString(),
    end_date: end.toISOString(),
  };
}

/** The `key_type` filter a consumption source implies, if any. */
export function sourceKeyType(source: UsageSource) {
  return source === "platform"
    ? ("platform-key" as const)
    : source === "owner"
      ? ("owner-key" as const)
      : undefined;
}

function cleanParams(params: Record<string, unknown>) {
  return Object.fromEntries(
    Object.entries(params).filter(
      ([, value]) => value !== undefined && value !== null && value !== "",
    ),
  );
}

async function fetchAggregate(
  ownerId: string,
  groupBy: UsageGroupBy[],
  period: UsagePeriod,
  filters: UsageFilters,
): Promise<AggregateResponse> {
  const response = await axios.get<AggregateResponse>(APIS.USAGE_AGGREGATE, {
    params: cleanParams({
      owner_id: ownerId,
      ...usageWindow(period),
      ...filters,
      group_by: groupBy,
    }),
    // group_by repeats as `group_by=model&group_by=provider`; the default
    // serializer would send `group_by[]=…` and the service would see no
    // grouping at all.
    paramsSerializer: { indexes: null },
  });
  return response.data;
}

/** One metric's total out of a group, defaulting to zero when absent. */
export function metricTotal(
  group: AggregateGroup | undefined,
  metric: UsageMetricName,
): number {
  return (
    group?.metrics.find((entry) => entry.metric_name === metric)?.total ?? 0
  );
}

/** One metric's average out of a group. `undefined` when the metric is absent. */
export function metricAvg(
  group: AggregateGroup | undefined,
  metric: UsageMetricName,
): number | undefined {
  return group?.metrics.find((entry) => entry.metric_name === metric)?.avg;
}

export interface UsageTotals {
  requests: number;
  total_tokens: number;
  input_tokens: number;
  output_tokens: number;
}

const EMPTY_TOTALS: UsageTotals = {
  requests: 0,
  total_tokens: 0,
  input_tokens: 0,
  output_tokens: 0,
};

function addTotals(into: UsageTotals, group: AggregateGroup): UsageTotals {
  return {
    requests: into.requests + (group.event_count ?? 0),
    total_tokens: into.total_tokens + metricTotal(group, "total_tokens"),
    input_tokens: into.input_tokens + metricTotal(group, "input_tokens"),
    output_tokens: into.output_tokens + metricTotal(group, "output_tokens"),
  };
}

export function sumGroups(groups: AggregateGroup[]): UsageTotals {
  return groups.reduce(addTotals, EMPTY_TOTALS);
}

/**
 * The account totals, and the platform/own-key split behind them.
 *
 * One call, grouped by `key_type` — this route publishes no ungrouped total
 * (rule 1 above), so a total here is necessarily the sum of one grouping, and
 * a separately-fetched one would be a second number that can disagree with its
 * own parts.
 *
 * The total is the sum of **every** group the answer carries, not of the two
 * named sides. Work billed to neither key — a `db_query` or a
 * `code_execution`, which run without a provider at all — comes back in its
 * own `key_type: null` bucket, exactly as rule 3 describes for `model` and
 * `provider`. Summing platform + owner would silently drop it: on the
 * knowledge service the same arithmetic lost 67 of 336 requests
 * (267 + 2 ≠ 336, verified live 2026-08-27). `platform + owner < total` is
 * therefore the normal case here, not a discrepancy to reconcile.
 */
export function useUsageTotals(
  period: UsagePeriod = DEFAULT_USAGE_PERIOD,
  source: UsageSource = "total",
  filters: UsageFilters = {},
) {
  const ownerId = useOwnerId();

  return useQuery({
    queryKey: ["usage", "totals", period, source, filters, ownerId],
    enabled: Boolean(ownerId),
    queryFn: async () => {
      const response = await fetchAggregate(
        ownerId as string,
        ["key_type"],
        period,
        filters,
      );
      const groups = response.groups ?? [];
      const platform = sumGroups(
        groups.filter((group) => group.key_type === "platform-key"),
      );
      const owner = sumGroups(
        groups.filter((group) => group.key_type === "owner-key"),
      );
      const total = sumGroups(groups);
      return {
        platform,
        owner,
        total,
        selected:
          source === "platform" ? platform : source === "owner" ? owner : total,
      };
    },
  });
}

/** Any breakdown the screen asks for, unmodified apart from the key_type filter. */
export function useUsageAggregate(
  groupBy: UsageGroupBy[],
  period: UsagePeriod = DEFAULT_USAGE_PERIOD,
  source: UsageSource = "total",
  filters: UsageFilters = {},
  enabled = true,
) {
  const ownerId = useOwnerId();
  const keyType = sourceKeyType(source);
  const merged: UsageFilters = {
    ...filters,
    ...(keyType ? { key_type: keyType } : {}),
  };

  return useQuery({
    queryKey: ["usage", "aggregate", groupBy, period, source, filters, ownerId],
    enabled: enabled && Boolean(ownerId),
    queryFn: () => fetchAggregate(ownerId as string, groupBy, period, merged),
  });
}

/**
 * Per-agent totals for the home screen's agent cards, keyed by `agent_id`.
 *
 * Grouped by agent over the default period; the names are not in the aggregate
 * and are joined from the agents list by the caller.
 */
export function useUsageByAgent() {
  const ownerId = useOwnerId();

  return useQuery({
    queryKey: ["usage", "by-agent", DEFAULT_USAGE_PERIOD, ownerId],
    enabled: Boolean(ownerId),
    queryFn: async (): Promise<Record<string, AgentUsage>> => {
      const response = await fetchAggregate(
        ownerId as string,
        ["agent_id"],
        DEFAULT_USAGE_PERIOD,
        {},
      );

      const byAgent: Record<string, AgentUsage> = {};
      for (const group of response.groups ?? []) {
        const agentId = group.agent_id;
        if (!agentId) continue;
        const current = byAgent[agentId] ?? {
          requests: 0,
          input_tokens: 0,
          output_tokens: 0,
        };
        byAgent[agentId] = {
          requests: current.requests + (group.event_count ?? 0),
          input_tokens:
            current.input_tokens + metricTotal(group, "input_tokens"),
          output_tokens:
            current.output_tokens + metricTotal(group, "output_tokens"),
        };
      }
      return byAgent;
    },
  });
}

/* ── the trend ──────────────────────────────────────────────────────────── */

export interface TrendBucket {
  bucket_start: string;
  bucket_end: string;
  event_count: number;
  metrics: Partial<Record<UsageMetricName, number>>;
}

export interface TrendResponse {
  bucket: UsageBucket;
  bucket_days: number;
  days: number;
  window_start: string;
  window_end: string;
  series: TrendBucket[];
}

/**
 * The series behind the trend chart.
 *
 * The response is dense and oldest-first: an empty bucket arrives as
 * `event_count: 0` with `metrics: {}`, and it is plotted as a zero. Dropping
 * empty buckets would draw a straight line across the gap and show usage that
 * never happened, so nothing here filters the series.
 *
 * Buckets are rolling blocks ending now, not calendar periods — `week` over 30
 * days is five buckets, `month` is one.
 */
export function useUsageTrend(
  period: UsagePeriod = DEFAULT_USAGE_PERIOD,
  source: UsageSource = "total",
  bucket: UsageBucket = "day",
  filters: UsageFilters = {},
) {
  const ownerId = useOwnerId();
  const keyType = sourceKeyType(source);

  return useQuery({
    queryKey: ["usage", "trend", period, source, bucket, filters, ownerId],
    enabled: Boolean(ownerId),
    queryFn: async () => {
      const response = await axios.get<TrendResponse>(APIS.USAGE_TREND, {
        params: cleanParams({
          owner_id: ownerId,
          days: periodDays(period),
          bucket,
          ...filters,
          ...(keyType ? { key_type: keyType } : {}),
        }),
      });
      return response.data;
    },
  });
}

/* ── the limits ─────────────────────────────────────────────────────────── */

/**
 * One limit, with its usage and its escape route already resolved server-side.
 *
 * Read `lifted` before `percent`. A lifted limit has `percent: null` and must
 * be drawn with no progress bar — a bar against a ceiling nobody enforces is a
 * lie the reader can act on. `maximum` still states the ceiling in words, so
 * "lifted" never costs the reader sight of what the cap actually is.
 *
 * `limit: null` is no limit at all: show `used` and the words, never a 0% bar.
 *
 * Only `enforced: true` blocks anything, and today that is `queries_per_day`
 * alone. Every other row is reporting, and drawing one as a blocker invents a
 * consequence that does not exist.
 */
export interface LimitItem {
  key: string;
  label: string;
  used: number;
  limit?: number | null;
  unit: string;
  /** The ceiling in words, stated whether or not it applies to this owner. */
  maximum: string;
  note: string;
  /** Providers whose own key would lift this limit. */
  lifted_by?: string[];
  /** Of those, the ones this owner already holds. */
  held?: string[];
  /** Of those, the ones this owner does not hold. */
  missing?: string[];
  lifted?: boolean;
  percent?: number | null;
  /** `plan` | `own-keys` | `plan-or-own-keys` — what moves this ceiling. */
  raises?: string;
  enforced?: boolean;
}

export interface LimitGroup {
  group: string;
  items: LimitItem[];
}

export interface OwnerLimits {
  owner_id: string;
  tier: { name: string; tier_type: string; is_default: boolean };
  billing_window: { days: number; start: string; end: string };
  own_credentials?: string[];
  /** Dollars per token, for every cost figure on the screen. */
  token_rate_usd: number;
  groups: LimitGroup[];
  exceeded?: string[];
}

/**
 * The whole Limits tab, in one read.
 *
 * Also the source of `token_rate_usd`, which is why the Overview reads it too:
 * cost is not returned by any usage endpoint and is computed as
 * `total_tokens × token_rate_usd`.
 */
export function useOwnerLimits() {
  return useQuery({
    queryKey: ["usage", "limits", ME],
    queryFn: async (): Promise<OwnerLimits> => {
      const url = buildApiUrl(APIS.OWNER_LIMITS, { owner_id: ME });
      const response = await axios.get<OwnerLimits>(url);
      return response.data;
    },
  });
}

/* ── the events ─────────────────────────────────────────────────────────── */

export interface UsageEvent {
  event_id: string;
  owner_id: string;
  key_type: string;
  agent_id?: string | null;
  service_type?: string;
  operation: string;
  label?: string | null;
  session_id?: string | null;
  request_id?: string | null;
  operation_id?: string | null;
  timestamp: string;
  metadata?: { provider?: string | null; model?: string | null } | null;
  metrics?: Array<{ name: string; value: number }>;
  created_at?: string;
}

export interface UsageEventsPage {
  total_count: number;
  limit: number;
  offset: number;
  events: UsageEvent[];
}

/** The raw event log behind every aggregate on this screen. */
export function useUsageEvents(
  period: UsagePeriod = DEFAULT_USAGE_PERIOD,
  source: UsageSource = "total",
  filters: Pick<UsageFilters, "agent_id" | "operation"> = {},
  page: { limit: number; offset: number } = { limit: 50, offset: 0 },
  enabled = true,
) {
  const ownerId = useOwnerId();
  const keyType = sourceKeyType(source);

  return useQuery({
    queryKey: ["usage", "events", period, source, filters, page, ownerId],
    enabled: enabled && Boolean(ownerId),
    queryFn: async () => {
      const response = await axios.get<UsageEventsPage>(APIS.USAGE_EVENTS, {
        params: cleanParams({
          owner_id: ownerId,
          ...usageWindow(period),
          ...filters,
          ...(keyType ? { key_type: keyType } : {}),
          limit: page.limit,
          offset: page.offset,
        }),
      });
      return response.data;
    },
  });
}

/* ── cost ───────────────────────────────────────────────────────────────── */

/**
 * Cost, from tokens and the workspace's own token rate.
 *
 * No endpoint returns cost. It is deliberately unrounded here and rounded only
 * for display: rounding before computing a percentage makes the cost bar and
 * the token bar disagree for identical usage, which is the one defect this
 * derivation exists to prevent.
 */
export function tokenCost(tokens: number, rate: number | undefined): number {
  return tokens * (rate ?? 0);
}

/** Omit a percentage when the earlier period was empty. */
export function usagePercentChange(
  current: number,
  previous: number,
): number | undefined {
  if (!previous) return undefined;
  return ((current - previous) / previous) * 100;
}
