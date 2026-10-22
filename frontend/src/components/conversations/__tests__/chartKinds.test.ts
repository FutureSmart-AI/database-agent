import { describe, expect, it } from "vitest";

import {
  availableKinds,
  CHART_KINDS,
  kindFromSuggestion,
  unavailableReason,
} from "../chartKinds";

describe("kindFromSuggestion", () => {
  it("reads the service's own wording", () => {
    expect(kindFromSuggestion("Bar Chart")).toBe("bar");
    expect(kindFromSuggestion("Line Chart")).toBe("line");
    expect(kindFromSuggestion("stacked area over time")).toBe("area");
    expect(kindFromSuggestion("Pie Chart")).toBe("pie");
    expect(kindFromSuggestion("Doughnut")).toBe("donut");
    expect(kindFromSuggestion("scatter plot")).toBe("scatter");
    expect(kindFromSuggestion("vertical bar chart")).toBe("column");
  });

  /** A donut suggestion often says "pie" as well; the hole is the specific bit. */
  it("prefers the more specific reading when both are named", () => {
    expect(kindFromSuggestion("pie / donut")).toBe("donut");
  });

  it('does not read a pie of "data points" as a scatter', () => {
    expect(kindFromSuggestion("Pie chart of the data points")).toBe("pie");
  });

  it("falls back to bars when the run suggested nothing usable", () => {
    expect(kindFromSuggestion(undefined)).toBe("bar");
    expect(kindFromSuggestion("")).toBe("bar");
    expect(kindFromSuggestion("something else entirely")).toBe("bar");
  });
});

describe("availability", () => {
  const positive = [
    { label: "a", value: 3 },
    { label: "b", value: 1 },
  ];
  const withNegative = [
    { label: "a", value: 3 },
    { label: "b", value: -1 },
  ];

  it("offers every reading of an all-positive result", () => {
    expect(availableKinds(positive)).toHaveLength(CHART_KINDS.length);
  });

  /**
   * A negative slice is not a small slice — recharts draws it at a size that
   * says the opposite of what the number does.
   */
  it("withholds the share readings when a value is negative", () => {
    const keys = availableKinds(withNegative).map((option) => option.key);
    expect(keys).not.toContain("pie");
    expect(keys).not.toContain("donut");
    expect(keys).toContain("bar");
    expect(unavailableReason("pie", withNegative)).toMatch(/negative/);
    expect(unavailableReason("bar", withNegative)).toBeNull();
  });
});
