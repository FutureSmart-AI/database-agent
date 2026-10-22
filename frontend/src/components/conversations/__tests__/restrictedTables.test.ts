import { describe, expect, it } from "vitest";

import { restrictedTablesInAnswer } from "../restrictedTables";

/**
 * Which tables an answer read that the agent is configured to exclude.
 *
 * Benchmark TC60: with `returns` marked Excluded in Settings, the agent
 * answered "the requested data source is restricted or not available" and the
 * screen drew the query and its rows underneath the refusal anyway. The screen
 * has the visibility flags already — this is what it compares them against.
 */
describe("restrictedTablesInAnswer", () => {
  it("names an excluded table the answer read", () => {
    expect(restrictedTablesInAnswer(["returns"], ["returns"])).toEqual([
      "returns",
    ]);
  });

  it("is quiet when every table read is included", () => {
    expect(
      restrictedTablesInAnswer(["orders", "customers"], ["returns"]),
    ).toEqual([]);
  });

  it("matches however the trace spells the name", () => {
    // The trace reports what the SQL said: schema-qualified, quoted, cased.
    expect(
      restrictedTablesInAnswer(
        ['public."Returns"', "public.orders"],
        ["returns"],
      ),
    ).toEqual(['public."Returns"']);
  });

  it("reports each excluded table once, in the order the answer read them", () => {
    expect(
      restrictedTablesInAnswer(
        ["returns", "orders", "public.returns", "payouts"],
        ["payouts", "returns"],
      ),
    ).toEqual(["returns", "payouts"]);
  });

  it("has nothing to say without both halves", () => {
    expect(restrictedTablesInAnswer([], ["returns"])).toEqual([]);
    expect(restrictedTablesInAnswer(["returns"], [])).toEqual([]);
    expect(restrictedTablesInAnswer(undefined, undefined)).toEqual([]);
  });
});
