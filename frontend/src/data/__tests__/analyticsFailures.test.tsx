import type { ReactNode } from "react";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FAILURE_CATEGORIES, useFailures } from "../analyticsFailures";

const get = vi.fn();
vi.mock("@/platform/utils/axios", () => ({
  default: { get: (...a: unknown[]) => get(...a) },
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const AGENT = "NL2SQL_7C4A91E2";
const WEEK = { mode: "preset", period: "week" } as const;

describe("useFailures", () => {
  beforeEach(() => get.mockReset());

  it("reads the NL2SQL-only failures route with the window", async () => {
    get.mockResolvedValue({ data: { total_failures: 12 } });
    const { result } = renderHook(() => useFailures(AGENT, WEEK), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(get).toHaveBeenCalledWith(
      `/nl2sql/api/v1/agents/${AGENT}/analytics/failures`,
      { params: { period: "week", limit: 50, offset: 0 } },
    );
    expect(result.current.data?.total_failures).toBe(12);
  });

  it("sends the category and stage filters only when set", async () => {
    get.mockResolvedValue({ data: { total_failures: 6 } });
    const { result } = renderHook(
      () =>
        useFailures(AGENT, WEEK, {
          category: "sql_error",
          failed_stage: "sql_exec",
        }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(get.mock.calls[0][1].params).toEqual({
      period: "week",
      category: "sql_error",
      failed_stage: "sql_exec",
      limit: 50,
      offset: 0,
    });
  });

  it("is disabled until the agent id is known", () => {
    const { result } = renderHook(() => useFailures(undefined, WEEK), {
      wrapper,
    });
    expect(get).not.toHaveBeenCalled();
    expect(result.current.fetchStatus).toBe("idle");
  });

  it("re-reads when the window changes", async () => {
    get.mockResolvedValue({ data: { total_failures: 1 } });
    const { rerender, result } = renderHook(
      ({ w }: { w: Parameters<typeof useFailures>[1] }) =>
        useFailures(AGENT, w),
      {
        wrapper,
        initialProps: { w: WEEK as Parameters<typeof useFailures>[1] },
      },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    rerender({ w: { mode: "preset", period: "month" } });
    await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
    expect(get.mock.calls[1][1].params).toMatchObject({ period: "month" });
  });
});

describe("FAILURE_CATEGORIES", () => {
  // The doc's vocabulary, and the owner each category points at — the whole
  // point of the badge is telling a model problem from an operator one.
  it("covers every documented category", () => {
    expect(Object.keys(FAILURE_CATEGORIES).sort()).toEqual(
      [
        "db_connection",
        "exception",
        "llm_error",
        "no_rows",
        "out_of_scope",
        "sql_error",
        "sql_generation",
        "unanswered",
      ].sort(),
    );
  });

  it("attributes each category to who can fix it", () => {
    expect(FAILURE_CATEGORIES.sql_error.owner).toBe("model");
    expect(FAILURE_CATEGORIES.db_connection.owner).toBe("operator");
    expect(FAILURE_CATEGORIES.no_rows.owner).toBe("schema");
    expect(FAILURE_CATEGORIES.llm_error.owner).toBe("infrastructure");
    expect(FAILURE_CATEGORIES.out_of_scope.owner).toBe("question");
    expect(FAILURE_CATEGORIES.exception.owner).toBe("us");
  });
});
