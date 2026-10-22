import type { ReactNode } from "react";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useAnalyticsOverview } from "../analyticsOverview";

const get = vi.fn();
vi.mock("@/platform/utils/axios", () => ({
  default: { get: (...a: unknown[]) => get(...a) },
}));

/**
 * One client for the file, built outside the component: a client created per
 * render throws the cache away on every re-render, so a query that settles
 * simply starts again and never reaches a terminal state.
 */
const client = new QueryClient({
  defaultOptions: { queries: { retry: false } },
});
const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={client}>{children}</QueryClientProvider>
);

const URL = "/nl2sql/api/v1/agents/analytics/overview";
const WEEK = { mode: "preset", period: "week" } as const;
/** Axios rejects with an Error carrying `response`; a bare object is not one. */
const httpError = (status: number) =>
  Object.assign(new Error(`HTTP ${status}`), { response: { status } });

const BODY = {
  total_agents: 2,
  summary: { total_queries: 73, total_cost: 0.18, cost_complete: false },
  agents: [],
};

describe("useAnalyticsOverview", () => {
  beforeEach(() => {
    get.mockReset();
    client.clear();
  });

  it("reads the fleet route with only the window by default", async () => {
    get.mockResolvedValue({ data: BODY });
    const { result } = renderHook(() => useAnalyticsOverview(WEEK), {
      wrapper,
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(get).toHaveBeenCalledWith(URL, { params: { period: "week" } });
    expect(result.current.data?.total_agents).toBe(2);
  });

  it("sends a custom range instead of a period", async () => {
    get.mockResolvedValue({ data: BODY });
    renderHook(
      () =>
        useAnalyticsOverview({
          mode: "custom",
          start: "2026-08-01",
          end: "2026-08-15",
        }),
      { wrapper },
    );
    await waitFor(() => expect(get).toHaveBeenCalled());
    expect(get.mock.calls[0][1].params).toEqual({
      start_date: "2026-08-01",
      end_date: "2026-08-15",
    });
  });

  it("sends sort, order, search and paging when they are set", async () => {
    get.mockResolvedValue({ data: BODY });
    renderHook(
      () =>
        useAnalyticsOverview(WEEK, {
          sort: "total_cost",
          order: "asc",
          q: "NL2SQL_7C",
          limit: 100,
          offset: 100,
        }),
      { wrapper },
    );
    await waitFor(() => expect(get).toHaveBeenCalled());
    expect(get.mock.calls[0][1].params).toEqual({
      period: "week",
      sort: "total_cost",
      order: "asc",
      q: "NL2SQL_7C",
      limit: 100,
      offset: 100,
    });
  });

  /**
   * A session caller is scoped to their own agents server-side. Sending
   * `owner_id` asks for someone else's and is rejected for anything but the
   * master key, so the hook has no way to pass one.
   */
  it("never sends owner_id", async () => {
    get.mockResolvedValue({ data: BODY });
    renderHook(() => useAnalyticsOverview(WEEK, { q: "x" }), { wrapper });
    await waitFor(() => expect(get).toHaveBeenCalled());
    expect(get.mock.calls[0][1].params).not.toHaveProperty("owner_id");
  });

  it("reads a 404 as an empty workspace, not a failure", async () => {
    get.mockRejectedValue(httpError(404));
    const { result } = renderHook(() => useAnalyticsOverview(WEEK), {
      wrapper,
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual({
      total_agents: 0,
      summary: { total_queries: 0, total_cost: 0, cost_complete: true },
      agents: [],
    });
  });

  // A 500 is retried twice before it settles, which is the point — unlike the
  // 4xx statuses, it can succeed on a second attempt.
  it("still surfaces a real failure", async () => {
    get.mockRejectedValue(httpError(500));
    const { result } = renderHook(() => useAnalyticsOverview(WEEK), {
      wrapper,
    });
    await waitFor(() => expect(result.current.isError).toBe(true), {
      timeout: 10_000,
    });
    expect(get).toHaveBeenCalledTimes(3);
  }, 15_000);
});
