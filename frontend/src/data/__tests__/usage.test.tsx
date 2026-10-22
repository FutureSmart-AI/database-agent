import type { ReactNode } from "react";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import axios from "@/platform/utils/axios";

import {
  periodDays,
  sumGroups,
  tokenCost,
  usagePercentChange,
  useOwnerLimits,
  useUsageAggregate,
  useUsageEvents,
  useUsageTotals,
  useUsageTrend,
  type AggregateGroup,
} from "../usage";

/**
 * The Usage & Limits reads, against the four routes `nl2sql/api/docs`
 * documents and the bodies the API contract states:
 *
 * - `GET /v1/aggregate`                → `{ group_by, groups: [{ <dim>, event_count, metrics }] }`
 * - `GET /v1/trend`                    → `{ bucket, days, series: [{ bucket_start, event_count, metrics }] }`
 * - `GET /v1/owners/{owner_id}/limits` → the whole Limits tab, plus `token_rate_usd`
 * - `GET /v1/events`                   → the raw event log
 *
 * The rules under test are the ones the contract asks callers not to
 * re-derive: no ungrouped total, no cost from the API, `group_by` repeated
 * rather than bracketed, and no `service_type` grouping.
 */

vi.mock("@/platform/utils/axios", () => ({
  default: { get: vi.fn(), post: vi.fn() },
}));

// `/v1/aggregate`, `/v1/trend` and `/v1/events` answer `owner_id=me` with an
// empty result set rather than the caller's data, so they are sent the viewer's
// email and stay disabled until the profile resolves. `ownerId` is a `let` so a
// test can take the profile away.
let ownerId: string | undefined = "someone@example.com";
vi.mock("../session", () => ({ useOwnerId: () => ownerId }));

const mockedGet = vi.mocked(axios.get);

/**
 * The query params of the n-th GET. axios types `params` as `unknown`, and
 * these assertions read named fields off it.
 */
type SentConfig = {
  params: Record<string, unknown>;
  paramsSerializer?: unknown;
};
const getCall = (n = 0) =>
  mockedGet.mock.calls[n] as unknown as [string, SentConfig | undefined];

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const metrics = (total: number, input: number, output: number) => [
  {
    metric_name: "total_tokens",
    total,
    avg: total,
    min: 0,
    max: total,
    count: 1,
  },
  {
    metric_name: "input_tokens",
    total: input,
    avg: input,
    min: 0,
    max: input,
    count: 1,
  },
  {
    metric_name: "output_tokens",
    total: output,
    avg: output,
    min: 0,
    max: output,
    count: 1,
  },
];

const byKeyType: AggregateGroup[] = [
  {
    key_type: "platform-key",
    event_count: 30,
    metrics: metrics(9_000, 8_000, 1_000),
  } as AggregateGroup,
  {
    key_type: "owner-key",
    event_count: 12,
    metrics: metrics(3_000, 2_600, 400),
  } as AggregateGroup,
  // Work billed to neither key — a `db_query` or a `code_execution` runs
  // without a provider at all — comes back in its own null bucket, the same
  // way `model` and `provider` do. A fixture without one lets the total be
  // read as platform + owner and hides everything that arithmetic drops.
  {
    key_type: null,
    event_count: 5,
    metrics: metrics(1_500, 1_400, 100),
  } as AggregateGroup,
];

beforeEach(() => {
  vi.clearAllMocks();
  ownerId = "someone@example.com";
});

describe("aggregate reads", () => {
  it("asks for one grouping and repeats group_by rather than bracketing it", async () => {
    mockedGet.mockResolvedValue({
      data: { group_by: ["model", "provider"], groups: [] },
    } as never);

    const { result } = renderHook(
      () => useUsageAggregate(["model", "provider"], "30d", "platform"),
      { wrapper },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const [url, config] = getCall();
    expect(url).toBe("/nl2sql/api/v1/aggregate");
    expect(config?.params.group_by).toEqual(["model", "provider"]);
    // `group_by[]=…` is not a grouping the service recognises, so the
    // serializer must drop the indexes.
    expect(config?.paramsSerializer).toEqual({ indexes: null });
    // A consumption source is a `key_type` filter, never a grouping.
    expect(config?.params.key_type).toBe("platform-key");
    // Not `me`: that returns an empty result set from this route, which reads
    // as "no usage" rather than as "wrong owner".
    expect(config?.params.owner_id).toBe("someone@example.com");
  });

  it("never asks the service to group by service_type", async () => {
    mockedGet.mockResolvedValue({
      data: { group_by: ["operation"], groups: [] },
    } as never);

    const { result } = renderHook(
      () => useUsageAggregate(["operation"], "7d", "total"),
      { wrapper },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const config = getCall()[1];
    expect(config?.params.group_by).not.toContain("service_type");
    // Total is no filter at all — the split comes from grouping, not from a
    // third request.
    expect(config?.params.key_type).toBeUndefined();
  });

  it("does not ask at all until the viewer's profile has resolved", async () => {
    ownerId = undefined;
    mockedGet.mockResolvedValue({
      data: { group_by: ["operation"], groups: [] },
    } as never);

    const { result } = renderHook(
      () => useUsageAggregate(["operation"], "30d", "total"),
      { wrapper },
    );

    // An unscoped request would come back empty and be indistinguishable from
    // a genuinely empty period, so the query waits instead of firing.
    expect(result.current.fetchStatus).toBe("idle");
    expect(mockedGet).not.toHaveBeenCalled();
  });
});

describe("account totals", () => {
  it("totals every bucket the grouping returns, not just the two named keys", async () => {
    mockedGet.mockResolvedValue({
      data: { group_by: ["key_type"], groups: byKeyType },
    } as never);

    const { result } = renderHook(() => useUsageTotals("30d", "total"), {
      wrapper,
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    // One call, not three: a separately-fetched total is a third number that
    // can disagree with its own parts.
    expect(mockedGet).toHaveBeenCalledTimes(1);
    expect(getCall()[1]?.params.group_by).toEqual(["key_type"]);

    const data = result.current.data!;
    expect(data.platform.total_tokens).toBe(9_000);
    expect(data.owner.total_tokens).toBe(3_000);
    // 9,000 + 3,000 + the 1,500 that answered to neither key.
    expect(data.total.total_tokens).toBe(13_500);
    // The rule the knowledge service stated outright: never compute the total
    // as platform + owner. Untyped work answers to neither, so the sum comes
    // up short — here by the whole null bucket.
    expect(data.total.total_tokens).toBeGreaterThan(
      data.platform.total_tokens + data.owner.total_tokens,
    );
    // `event_count` is the Requests figure: 30 + 12 + 5.
    expect(data.total.requests).toBe(47);
    expect(data.selected).toEqual(data.total);
  });

  it("selects one side without a second request", async () => {
    mockedGet.mockResolvedValue({
      data: { group_by: ["key_type"], groups: byKeyType },
    } as never);

    const { result } = renderHook(() => useUsageTotals("30d", "owner"), {
      wrapper,
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(mockedGet).toHaveBeenCalledTimes(1);
    expect(result.current.data!.selected.total_tokens).toBe(3_000);
  });

  it("sums groups whose metrics are missing rather than dropping them", () => {
    const totals = sumGroups([
      { operation: "db_query", event_count: 7, metrics: [] } as AggregateGroup,
      ...byKeyType,
    ]);
    // 7 + 30 + 12 + 5, and 9,000 + 3,000 + 1,500: the metric-less group adds
    // its own event count and nothing else.
    expect(totals.requests).toBe(54);
    expect(totals.total_tokens).toBe(13_500);
  });
});

describe("the trend", () => {
  it("asks for days and a bucket, and keeps every bucket the service sent", async () => {
    const series = [
      {
        bucket_start: "2026-07-27T10:14:02+00:00",
        bucket_end: "2026-07-28T10:14:02+00:00",
        event_count: 0,
        metrics: {},
      },
      {
        bucket_start: "2026-08-25T10:14:02+00:00",
        bucket_end: "2026-08-26T10:14:02+00:00",
        event_count: 12,
        metrics: { total_tokens: 8_421 },
      },
    ];
    mockedGet.mockResolvedValue({
      data: { bucket: "day", bucket_days: 1, days: 30, series },
    } as never);

    const { result } = renderHook(() => useUsageTrend("30d", "total", "week"), {
      wrapper,
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const [url, config] = getCall();
    expect(url).toBe("/nl2sql/api/v1/trend");
    expect(config?.params.days).toBe(30);
    expect(config?.params.bucket).toBe("week");
    // No date range: `/v1/trend` takes `days`, and sending both would describe
    // two windows.
    expect(config?.params.start_date).toBeUndefined();
    // The empty bucket survives — dropping it would draw a straight line
    // across the gap and show usage that never happened.
    expect(result.current.data!.series).toHaveLength(2);
    expect(result.current.data!.series[0].event_count).toBe(0);
  });

  it("maps each period to the days the service counts", () => {
    expect(periodDays("7d")).toBe(7);
    expect(periodDays("30d")).toBe(30);
    expect(periodDays("90d")).toBe(90);
  });
});

describe("limits and cost", () => {
  it("reads the whole Limits tab from one owner-scoped route", async () => {
    mockedGet.mockResolvedValue({
      data: { owner_id: "me", token_rate_usd: 3.8e-6, groups: [] },
    } as never);

    const { result } = renderHook(() => useOwnerLimits(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    // `/limits` is the one route that does resolve `me` from the session.
    expect(mockedGet.mock.calls[0][0]).toBe("/nl2sql/api/v1/owners/me/limits");
  });

  it("prices tokens at the workspace rate without rounding", () => {
    // Unrounded on purpose: rounding before a percentage makes the cost bar
    // and the token bar disagree for identical usage.
    expect(tokenCost(55_755, 3.8e-6)).toBeCloseTo(0.211869, 10);
    // No rate yet is no cost claim, not a free period.
    expect(tokenCost(55_755, undefined)).toBe(0);
  });

  it("pages the raw event log over the same window as the cards", async () => {
    // The fourth route in the contract. No element of this design renders the
    // log yet — the query log lives on the per-agent Analytics screen — but the
    // read is here and window-aligned, so a log added later cannot quietly
    // describe a different period from the figures above it.
    mockedGet.mockResolvedValue({
      data: { total_count: 143, limit: 50, offset: 0, events: [] },
    } as never);

    const { result } = renderHook(
      () =>
        useUsageEvents(
          "7d",
          "platform",
          { operation: "llm_call" },
          {
            limit: 50,
            offset: 100,
          },
        ),
      { wrapper },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const [url, config] = getCall();
    expect(url).toBe("/nl2sql/api/v1/events");
    expect(config?.params).toMatchObject({
      owner_id: "someone@example.com",
      operation: "llm_call",
      key_type: "platform-key",
      limit: 50,
      offset: 100,
    });
    expect(config?.params.start_date).toBeTypeOf("string");
  });

  it("omits a delta for an empty earlier period", () => {
    expect(usagePercentChange(250, 0)).toBeUndefined();
    expect(usagePercentChange(250, 200)).toBe(25);
  });
});
