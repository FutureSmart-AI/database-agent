import { describe, expect, it } from "vitest";

import { normalizeResultChart } from "../normalizeResultChart";
import { toChartPoints } from "../toChartPoints";
import root from "./fixtures/root-stacked-installation.json";

const stacked = (data: unknown, metadata: Record<string, unknown> = {}) => ({
  suggestion: "Stacked Bar Chart",
  data,
  metadata,
});

describe("typed result-chart boundary", () => {
  it("preserves the exact root failure as two indices and two distinct series", () => {
    const before = JSON.stringify(root);
    const result = normalizeResultChart(root.chart);
    expect(result?.shape).toBe("stacked");
    if (result?.shape !== "stacked") throw new Error("Expected stacked chart");
    expect(result.chart.rows).toEqual([
      { label: "North", values: { series_0: 250 } },
      { label: "South", values: { series_1: 200 } },
    ]);
    expect(result.chart.series.map((s) => s.label)).toEqual(["North", "South"]);
    expect(result.chart.orientation).toBe("horizontal");
    expect(JSON.stringify(root)).toBe(before);
  });

  it("keeps unseen series, zero, negative, fractional and missing values distinct", () => {
    const result = normalizeResultChart(
      stacked(
        [
          {
            index: "April",
            segments: [
              { category: "Online", value: 42.75 },
              { category: "Retail", value: -8.25 },
              { category: "Returns", value: 0 },
            ],
          },
          {
            index: "May",
            segments: [
              { category: "Online", value: 0 },
              { category: "Wholesale", value: 13 },
            ],
          },
        ],
        { chart_orientation: "vertical" },
      ),
    );
    if (result?.shape !== "stacked") throw new Error("Expected stacked chart");
    expect(result.chart.series.map((s) => s.label)).toEqual([
      "Online",
      "Retail",
      "Returns",
      "Wholesale",
    ]);
    expect(result.chart.rows).toEqual([
      {
        label: "April",
        values: { series_0: 42.75, series_1: -8.25, series_2: 0 },
      },
      { label: "May", values: { series_0: 0, series_3: 13 } },
    ]);
    expect(Object.hasOwn(result.chart.rows[1].values, "series_1")).toBe(false);
    expect(result.chart.orientation).toBe("vertical");
  });

  it("does not interpret source series labels as object paths or overwrite category labels", () => {
    const result = normalizeResultChart(
      stacked([
        {
          index: "label",
          segments: [
            { category: "label", value: 1 },
            { category: "a.b", value: 2 },
            { category: "__proto__", value: 3 },
          ],
        },
      ]),
    );
    if (result?.shape !== "stacked") throw new Error("Expected stacked chart");
    expect(result.chart.rows[0]).toEqual({
      label: "label",
      values: { series_0: 1, series_1: 2, series_2: 3 },
    });
    expect(result.chart.series.map((s) => s.label)).toEqual([
      "label",
      "a.b",
      "__proto__",
    ]);
  });

  it("retains all-zero normal data and original values in percent mode", () => {
    const zero = normalizeResultChart(
      stacked([
        { index: "Empty week", segments: [{ category: "Orders", value: 0 }] },
      ]),
    );
    expect(zero?.shape).toBe("stacked");
    if (zero?.shape === "stacked")
      expect(zero.chart.rows[0].values.series_0).toBe(0);
    const percent = normalizeResultChart(
      stacked(
        [
          {
            index: "Day",
            segments: [
              { category: "One", value: 1 },
              { category: "Three", value: 3 },
            ],
          },
        ],
        { stack_type: "percent" },
      ),
    );
    if (percent?.shape !== "stacked") throw new Error("Expected percent chart");
    expect(percent.chart.mode).toBe("percent");
    expect(percent.chart.rows[0].values).toEqual({ series_0: 1, series_1: 3 });
  });

  it.each([
    { data: [{ index: "A", segments: [{ category: "x", value: null }] }] },
    { data: [{ index: "A", segments: [{ category: "x", value: "2" }] }] },
    { data: [{ index: "A", segments: [{ category: "x", value: Infinity }] }] },
    {
      data: [
        {
          index: "A",
          segments: [
            { category: "x", value: 1 },
            { category: "x", value: 2 },
          ],
        },
      ],
    },
    {
      data: [
        { index: "A", segments: [{ category: "x", value: 1 }] },
        { index: "A", segments: [{ category: "y", value: 2 }] },
      ],
    },
    { data: [{ index: "A", value: 1 }] },
    { data: [] },
    {
      data: [{ index: "A", segments: [{ category: "x", value: -1 }] }],
      metadata: { stack_type: "percent" },
    },
    {
      data: [{ index: "A", segments: [{ category: "x", value: 0 }] }],
      metadata: { stack_type: "percent" },
    },
    {
      data: [{ index: "A", segments: [{ category: "x", value: 1 }] }],
      metadata: { stack_type: "unknown" },
    },
  ])(
    "reports malformed/undefined stacked semantics instead of dropping or fabricating values: %o",
    ({ data, metadata }) => {
      expect(normalizeResultChart(stacked(data, metadata))?.shape).toBe(
        "invalid",
      );
    },
  );

  it("preserves existing flat and columnar conversion exactly", () => {
    for (const input of [
      {
        suggestion: "Bar Chart",
        data: [
          { category: "City A", value: 14 },
          { category: "City B", value: 0 },
        ],
      },
      { suggestion: "Line Chart", data: { x: ["Mon", "Tue"], y: [2, -3] } },
    ])
      expect(normalizeResultChart(input)).toEqual({
        shape: "flat",
        chart: toChartPoints(input),
      });
    expect(normalizeResultChart(undefined)).toBeNull();
  });
});
