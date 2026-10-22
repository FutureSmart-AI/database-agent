import type { UseQueryResult } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { FailuresResponse } from "@/data/analyticsFailures";
import type { Scorecard } from "@/platform/analytics/types";

import FailuresTab from "../tabs/FailuresTab";

const useFailures = vi.fn();
vi.mock("@/data/analyticsFailures", async () => {
  const actual = await vi.importActual<
    typeof import("@/data/analyticsFailures")
  >("@/data/analyticsFailures");
  return { ...actual, useFailures: (...a: unknown[]) => useFailures(...a) };
});
vi.mock("../charts/FailureBreakdownChart", () => ({
  default: () => <div>chart</div>,
}));

const row = (i: number) => ({
  query_norm: `question ${i}`,
  failure_category: "sql_error",
  failed_stage: "sql_exec",
  occurrences: 2,
  first_seen: null,
  last_seen: null,
  sample_failure_detail: null,
});

/** `n` rows — a full page is what tells the UI another page may exist. */
function answer(n: number): Partial<UseQueryResult<FailuresResponse>> {
  return {
    data: {
      total_failures: 120,
      by_category: [],
      by_stage: [],
      top_failed_queries: Array.from({ length: n }, (_, i) => row(i)),
    },
    isLoading: false,
    isError: false,
    isFetching: false,
  };
}

const props = {
  scorecard: {
    data: { usage: { total_queries: 200 } },
    isLoading: false,
  } as unknown as UseQueryResult<Scorecard>,
  window: { mode: "preset", period: "week" } as const,
  agentId: "NL2SQL_1",
};

const lastOpts = () =>
  useFailures.mock.calls.at(-1)?.[2] as Record<string, unknown>;

describe("FailuresTab paging", () => {
  beforeEach(() => useFailures.mockReset());

  it("asks for the spec's default page on first render", () => {
    useFailures.mockReturnValue(answer(50));
    render(<FailuresTab {...props} />);
    // `/failures` publishes limit default 50, offset 0.
    expect(lastOpts()).toMatchObject({ limit: 50, offset: 0 });
  });

  it("advances the offset by a page", () => {
    useFailures.mockReturnValue(answer(50));
    render(<FailuresTab {...props} />);
    fireEvent.click(screen.getByLabelText("Next page"));
    expect(lastOpts()).toMatchObject({ limit: 50, offset: 50 });
  });

  /**
   * The endpoint reports no total for this list — only `total_failures`, which
   * counts failures rather than the distinct questions they group into. A short
   * page is the only evidence there is no next one.
   */
  it("offers no pagination when the first page is short", () => {
    useFailures.mockReturnValue(answer(3));
    render(<FailuresTab {...props} />);
    expect(screen.queryByLabelText("Next page")).not.toBeInTheDocument();
  });

  it("counts distinct questions as a lower bound while pages remain", () => {
    useFailures.mockReturnValue(answer(50));
    render(<FailuresTab {...props} />);
    expect(screen.getByText("≥50")).toBeInTheDocument();
  });
});
