import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { TrendBucket } from "@/data/usage";

import UsageTrendChart, { bucketValue } from "../UsageTrendChart";

/**
 * The trend, against `/v1/trend`'s own response shape.
 *
 * The one rule that matters here: the series is dense, and every bucket is
 * plotted. An empty bucket arrives as `event_count: 0` with `metrics: {}`, and
 * skipping it would let the line draw straight across the gap and show usage
 * that never happened.
 */

const series: TrendBucket[] = [
  {
    bucket_start: "2026-08-24T10:14:02+00:00",
    bucket_end: "2026-08-25T10:14:02+00:00",
    event_count: 0,
    metrics: {},
  },
  {
    bucket_start: "2026-08-25T10:14:02+00:00",
    bucket_end: "2026-08-26T10:14:02+00:00",
    event_count: 12,
    metrics: { total_tokens: 8_421, input_tokens: 8_100, output_tokens: 321 },
  },
];

describe("bucketValue", () => {
  it("reads an empty bucket as zero rather than as no data", () => {
    expect(bucketValue(series[0], "total_tokens", 3.8e-6)).toBe(0);
    expect(bucketValue(series[0], "requests", 3.8e-6)).toBe(0);
    expect(bucketValue(series[0], "cost", 3.8e-6)).toBe(0);
  });

  it("takes Requests from event_count and the rest from metrics", () => {
    expect(bucketValue(series[1], "requests", 3.8e-6)).toBe(12);
    expect(bucketValue(series[1], "total_tokens", 3.8e-6)).toBe(8_421);
    expect(bucketValue(series[1], "input_tokens", 3.8e-6)).toBe(8_100);
    expect(bucketValue(series[1], "output_tokens", 3.8e-6)).toBe(321);
  });

  it("derives cost from the workspace's token rate, since no endpoint returns it", () => {
    expect(bucketValue(series[1], "cost", 3.8e-6)).toBeCloseTo(0.0319998, 10);
    // No rate yet is no cost claim, not a free bucket.
    expect(bucketValue(series[1], "cost", undefined)).toBe(0);
  });
});

describe("UsageTrendChart", () => {
  const props = {
    series,
    metric: "total_tokens" as const,
    onMetricChange: vi.fn(),
    granularity: "day" as const,
    onGranularityChange: vi.fn(),
    tokenRate: 3.8e-6,
    periodLabel: "Last 30 days",
    sourceLabel: "Total Consumptions",
  };

  it("offers only the three buckets the endpoint accepts", () => {
    render(<UsageTrendChart {...props} />);

    expect(
      Array.from(
        screen.getByLabelText("Trend granularity").querySelectorAll("option"),
      ).map((option) => option.value),
    ).toEqual(["day", "week", "month"]);
  });

  it("offers every metric the aggregate carries, plus derived cost", () => {
    render(<UsageTrendChart {...props} />);

    expect(
      Array.from(
        screen.getByLabelText("Trend metric").querySelectorAll("option"),
      ).map((option) => option.value),
    ).toEqual([
      "total_tokens",
      "input_tokens",
      "output_tokens",
      "requests",
      "cost",
    ]);
  });

  it("names the period and source it is drawn for", () => {
    render(<UsageTrendChart {...props} />);

    expect(screen.getByText("Usage Trends")).toBeInTheDocument();
    expect(
      screen.getByText("Last 30 days · Total Consumptions"),
    ).toBeInTheDocument();
  });

  it("says the window is empty rather than drawing an empty axis", () => {
    render(<UsageTrendChart {...props} series={[]} />);

    expect(
      screen.getByText("No usage recorded in this window."),
    ).toBeInTheDocument();
  });
});
