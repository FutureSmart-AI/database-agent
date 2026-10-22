import { describe, expect, it } from "vitest";

import { ANALYTICS_CONTRACT } from "../../generated/analyticsContract";
import {
  contractNumber,
  humanizeCode,
  NL2SQL_FAILURE_OPTIONS,
  NL2SQL_FILTER_OPTIONS,
  NL2SQL_LIMITS,
  NL2SQL_OVERVIEW_OPTIONS,
  pageSizeLadder,
} from "../analyticsContractOptions";

describe("humanizeCode", () => {
  it("title-cases a snake_case code as a phrase", () => {
    expect(humanizeCode("direct_answer")).toBe("Direct answer");
    expect(humanizeCode("no_rows")).toBe("No rows");
  });

  it("uppercases initialisms wherever they fall", () => {
    expect(humanizeCode("sql")).toBe("SQL");
    expect(humanizeCode("cross_db")).toBe("Cross DB");
    expect(humanizeCode("sql_error")).toBe("SQL error");
  });

  it("labels a code it has never seen without dropping it", () => {
    expect(humanizeCode("some_new_route")).toBe("Some new route");
  });
});

describe("NL2SQL_FILTER_OPTIONS", () => {
  /**
   * The regression this whole layer exists for: these values used to be the
   * agent dashboard's service families, which NL2SQL's `route` does not
   * accept, so every choice returned an empty log.
   */
  it("takes routes from the service's own spec", () => {
    expect(NL2SQL_FILTER_OPTIONS.routes.map((o) => o.value)).toEqual([
      ...ANALYTICS_CONTRACT.queries.route.values,
    ]);
    expect(NL2SQL_FILTER_OPTIONS.routes.map((o) => o.value)).not.toContain(
      "knowledge",
    );
  });

  it("sends full-word feedback values and drops the redundant 'any'", () => {
    expect(NL2SQL_FILTER_OPTIONS.feedback.map((o) => o.value)).toEqual([
      "positive",
      "negative",
      "none",
    ]);
  });

  it("takes outcomes, buckets and cost strategies from the spec", () => {
    expect(NL2SQL_FILTER_OPTIONS.outcomes.map((o) => o.value)).toEqual([
      "success",
      "failure",
    ]);
    expect(NL2SQL_FILTER_OPTIONS.buckets.map((o) => o.value)).toEqual([
      "hour",
      "day",
      "week",
      "month",
    ]);
    expect(NL2SQL_FILTER_OPTIONS.costStrategies.map((o) => o.value)).toEqual([
      "run_id",
      "metadata",
      "both",
    ]);
  });
});

describe("limits", () => {
  it("takes top_n and page sizes from the spec's own defaults", () => {
    expect(NL2SQL_LIMITS.scorecardTopN).toBe(
      ANALYTICS_CONTRACT.scorecard.top_n.default,
    );
    expect(NL2SQL_LIMITS.queriesPageSize).toBe(
      ANALYTICS_CONTRACT.queries.limit.default,
    );
    expect(NL2SQL_LIMITS.failuresPageSize).toBe(
      ANALYTICS_CONTRACT.failures.limit.default,
    );
  });

  it("never offers a page larger than the endpoint's cap", () => {
    for (const [endpoint, sizes] of [
      ["queries", NL2SQL_FILTER_OPTIONS.rowsPerPage],
      ["failures", NL2SQL_FAILURE_OPTIONS.pageSizes],
      ["overview", NL2SQL_OVERVIEW_OPTIONS.pageSizes],
    ] as const) {
      const cap = contractNumber(endpoint, "limit", "max", Infinity);
      expect(Math.max(...sizes)).toBeLessThanOrEqual(cap);
      expect(Math.min(...sizes)).toBeGreaterThan(0);
    }
  });

  it("builds the ladder from the endpoint's default and cap", () => {
    // /queries: default 20, cap 100.
    expect(pageSizeLadder("queries")).toEqual([20, 40, 100]);
  });
});
