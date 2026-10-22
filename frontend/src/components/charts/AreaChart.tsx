"use client";

import {
  Area,
  CartesianGrid,
  AreaChart as RechartsAreaChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { CHART, TOOLTIP_STYLE } from "@/lib/colors";
import { compact } from "@/lib/format";

import type { BarDatum } from "./BarChart";
import { CATEGORY_HEIGHT, LABEL_MAX_CHARS, shouldAngle } from "./constants";

interface AreaChartProps {
  data: BarDatum[];
  title?: string;
}

const truncate = (label: string) =>
  label.length > LABEL_MAX_CHARS
    ? `${label.slice(0, LABEL_MAX_CHARS - 1)}…`
    : label;

/**
 * A filled trend — the line chart's reading of a result, with the area under
 * it shaded so the magnitude, not just the shape, carries.
 *
 * One series only: this draws the single measure a NL2SQL answer returns, so
 * there is no stacking to get wrong.
 */
export default function AreaChart({ data, title }: AreaChartProps) {
  if (!data.length) return null;

  const angled = shouldAngle(data.map((datum) => datum.label));

  return (
    <ResponsiveContainer width="100%" height={CATEGORY_HEIGHT}>
      <RechartsAreaChart
        data={data}
        // An angled label starts above and right of its tick, and the last
        // tick sits on the container's edge — hence the wider right gutter.
        margin={{
          top: 12,
          right: angled ? 40 : 16,
          left: 0,
          bottom: angled ? 44 : 8,
        }}
        aria-label={`${title || "Chart"} — area chart, ${data.length} points`}
      >
        <defs>
          <linearGradient id="n2s-area-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={CHART.primary} stopOpacity={0.28} />
            <stop offset="100%" stopColor={CHART.primary} stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} />
        <XAxis
          dataKey="label"
          stroke={CHART.axis}
          fontSize={11}
          tickLine={false}
          axisLine={false}
          interval={0}
          angle={angled ? -35 : 0}
          textAnchor={angled ? "end" : "middle"}
          height={angled ? 56 : 24}
          tickFormatter={truncate}
        />
        <YAxis
          stroke={CHART.axis}
          fontSize={11}
          width={60}
          tickLine={false}
          axisLine={false}
          tickFormatter={compact}
        />
        <Tooltip
          formatter={(value: number) => [compact(value), title ?? "Value"]}
          contentStyle={TOOLTIP_STYLE}
        />
        <Area
          type="monotone"
          dataKey="value"
          name={title ?? "Value"}
          stroke={CHART.primary}
          strokeWidth={2}
          fill="url(#n2s-area-fill)"
          dot={data.length <= 24 ? { r: 2.5, strokeWidth: 0 } : false}
          activeDot={{ r: 4 }}
        />
      </RechartsAreaChart>
    </ResponsiveContainer>
  );
}
