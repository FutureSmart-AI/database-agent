"use client";

import dayjs from "dayjs";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { TrendBucket, UsageBucket } from "@/data/usage";
import { Select } from "@/platform/components/ui";

import { TREND_GRANULARITY_OPTIONS, TREND_METRIC_OPTIONS } from "./constants";

export type TrendMetric =
  "total_tokens" | "input_tokens" | "output_tokens" | "requests" | "cost";

function compact(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return Math.round(value).toLocaleString("en-US");
}

function formatValue(metric: TrendMetric, value: number): string {
  return metric === "cost"
    ? `$${value.toFixed(value < 0.01 ? 4 : 2)}`
    : compact(value);
}

/**
 * A bucket's label.
 *
 * Buckets are rolling blocks ending at `bucket_end`, not calendar periods, so a
 * weekly bucket is named by the day it ends on rather than by a week number
 * that would not line up with any calendar week.
 */
function bucketLabel(bucket: TrendBucket, granularity: UsageBucket): string {
  const end = dayjs(bucket.bucket_end);
  if (granularity === "month") return end.format("MMM YYYY");
  if (granularity === "week") return `Week to ${end.format("D MMM")}`;
  return dayjs(bucket.bucket_start).format("D MMM");
}

/**
 * One bucket's value for the selected metric.
 *
 * `metrics` is `{}` on an empty bucket, and that reads as a zero rather than a
 * gap — a missing point would let the line draw straight across the gap and
 * show usage that never happened.
 */
export function bucketValue(
  bucket: TrendBucket,
  metric: TrendMetric,
  tokenRate: number | undefined,
): number {
  if (metric === "requests") return bucket.event_count ?? 0;
  if (metric === "cost")
    return (bucket.metrics.total_tokens ?? 0) * (tokenRate ?? 0);
  return bucket.metrics[metric] ?? 0;
}

export default function UsageTrendChart({
  series,
  metric,
  onMetricChange,
  granularity,
  onGranularityChange,
  tokenRate,
  periodLabel,
  sourceLabel,
  isLoading,
}: {
  /** The dense series exactly as `/v1/trend` returned it, oldest first. */
  series: TrendBucket[];
  metric: TrendMetric;
  onMetricChange: (metric: TrendMetric) => void;
  granularity: UsageBucket;
  onGranularityChange: (granularity: UsageBucket) => void;
  tokenRate: number | undefined;
  periodLabel: string;
  sourceLabel: string;
  isLoading?: boolean;
}) {
  // Every bucket is plotted, zeros included, in the order the service sent
  // them. Nothing is filtered and nothing is re-sorted.
  const data = series.map((bucket) => ({
    label: bucketLabel(bucket, granularity),
    value: bucketValue(bucket, metric, tokenRate),
  }));

  return (
    <section className="overflow-hidden rounded-xl border border-black/5 bg-white shadow-sm">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-slate-100 px-4 py-3.5 sm:px-6">
        <div>
          <h2 className="text-sm font-bold text-slate-900">Usage Trends</h2>
          <p className="mt-0.5 text-xs text-slate-400">
            {periodLabel} · {sourceLabel}
          </p>
        </div>
        <div className="ml-auto flex flex-wrap gap-3">
          <label className="flex min-w-36 flex-col gap-1 text-[11px] font-semibold text-slate-500">
            Metric
            <Select
              aria-label="Trend metric"
              value={metric}
              onChange={(value) => onMetricChange(value as TrendMetric)}
              options={TREND_METRIC_OPTIONS}
              fullWidth={false}
              className="w-36"
            />
          </label>
          <label className="flex min-w-36 flex-col gap-1 text-[11px] font-semibold text-slate-500">
            Granularity
            <Select
              aria-label="Trend granularity"
              value={granularity}
              onChange={(value) => onGranularityChange(value as UsageBucket)}
              options={TREND_GRANULARITY_OPTIONS}
              fullWidth={false}
              className="w-36"
            />
          </label>
        </div>
      </div>

      <div className="h-64 p-4" aria-busy={isLoading}>
        {isLoading ? (
          <div className="h-full animate-pulse rounded-lg bg-slate-50" />
        ) : !data.length ? (
          <div className="flex h-full items-center justify-center text-sm text-slate-400">
            No usage recorded in this window.
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 12, right: 12, left: 0 }}>
              <CartesianGrid stroke="#e2e8f0" vertical={false} />
              <XAxis
                dataKey="label"
                axisLine={false}
                tickLine={false}
                tick={{ fill: "#94a3b8", fontSize: 11 }}
                minTickGap={28}
              />
              <YAxis
                axisLine={false}
                tickLine={false}
                tick={{ fill: "#94a3b8", fontSize: 11 }}
                tickFormatter={(value) => formatValue(metric, value)}
                width={54}
              />
              <Tooltip
                formatter={(value) => formatValue(metric, Number(value))}
                labelFormatter={(label) => String(label)}
                contentStyle={{
                  border: "1px solid #e2e8f0",
                  borderRadius: "8px",
                  boxShadow: "0 4px 12px rgb(15 23 42 / 12%)",
                }}
              />
              <Line
                type="monotone"
                dataKey="value"
                name={
                  TREND_METRIC_OPTIONS.find((option) => option.value === metric)
                    ?.label ?? metric
                }
                stroke="#2563eb"
                strokeWidth={2}
                dot={{ r: 2.5, fill: "#2563eb", strokeWidth: 0 }}
                activeDot={{ r: 4 }}
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
    </section>
  );
}
