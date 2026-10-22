import { describe, expect, it } from "vitest";

import { toChartPoints } from "../toChartPoints";

describe("toChartPoints", () => {
  it("reads the row-array shape", () => {
    const render = toChartPoints({
      suggestion: "bar chart",
      data: [
        { x: "North", y: 120 },
        { x: "South", y: 80 },
      ],
    });
    expect(render).toEqual({
      kind: "bar",
      points: [
        { label: "North", value: 120 },
        { label: "South", value: 80 },
      ],
      xLabel: undefined,
      yLabel: undefined,
    });
  });

  it("reads the columnar shape line charts use", () => {
    const render = toChartPoints({
      suggestion: "line chart",
      data: { x: ["Jan", "Feb"], y: [10, 20] },
    });
    expect(render?.kind).toBe("line");
    expect(render?.points).toEqual([
      { label: "Jan", value: 10 },
      { label: "Feb", value: 20 },
    ]);
  });

  it("carries the axis labels the service supplied", () => {
    const render = toChartPoints({
      suggestion: "bar",
      data: [{ x: "a", y: 1 }],
      metadata: { x_axis: { label: "Region" }, y_axis: { label: "Revenue" } },
    });
    expect(render?.xLabel).toBe("Region");
    expect(render?.yLabel).toBe("Revenue");
  });

  it("coerces numeric strings and drops rows with no number", () => {
    const render = toChartPoints({
      suggestion: "bar",
      data: [
        { x: "a", y: "1,200" },
        { x: "b", y: null },
      ],
    });
    expect(render?.points).toEqual([{ label: "a", value: 1200 }]);
  });

  it("falls back to the row position when a label is missing", () => {
    const render = toChartPoints({ suggestion: "bar", data: [{ y: 5 }] });
    expect(render?.points[0].label).toBe("1");
  });

  it("returns null when there is nothing to draw", () => {
    expect(toChartPoints(undefined)).toBeNull();
    expect(toChartPoints({ suggestion: "bar", data: [] })).toBeNull();
    expect(
      toChartPoints({ suggestion: "bar", data: { x: [], y: [] } }),
    ).toBeNull();
  });
});
