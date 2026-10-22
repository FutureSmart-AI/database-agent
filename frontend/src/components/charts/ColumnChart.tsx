"use client";

import {
  Bar,
  CartesianGrid,
  Cell,
  BarChart as RechartsBarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { CHART, TOOLTIP_STYLE } from "@/lib/colors";
import { compact } from "@/lib/format";

import type { BarDatum } from "./BarChart";
import { CATEGORY_HEIGHT, LABEL_MAX_CHARS, shouldAngle } from "./constants";

interface ColumnChartProps {
  data: BarDatum[];
  title?: string;
  /** Colour per bar, for a result read as categories rather than one measure. */
  colorOf?: (index: number) => string;
}

const truncate = (label: string) =>
  label.length > LABEL_MAX_CHARS
    ? `${label.slice(0, LABEL_MAX_CHARS - 1)}…`
    : label;

/**
 * Vertical bars — the same result as `BarChart`, stood up.
 *
 * Horizontal bars give a long category name room to be read; columns give a
 * sequence (months, buckets, anything ordered) the left-to-right reading that
 * a rotated axis loses. Which of the two a result wants is the reader's call,
 * so both are offered rather than one being picked for them.
 */
export default function ColumnChart({
  data,
  title,
  colorOf,
}: ColumnChartProps) {
  if (!data.length) return null;

  const angled = shouldAngle(data.map((datum) => datum.label));

  return (
    <ResponsiveContainer width="100%" height={CATEGORY_HEIGHT}>
      <RechartsBarChart
        data={data}
        margin={{
          top: 12,
          right: angled ? 24 : 12,
          left: 0,
          bottom: angled ? 44 : 8,
        }}
        aria-label={`${title || "Chart"} — column chart, ${data.length} values`}
      >
        <CartesianGrid vertical={false} stroke={CHART.grid} />
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
          cursor={{ fill: "#6366f10D" }}
          formatter={(value: number) => [compact(value), title ?? "Value"]}
          contentStyle={TOOLTIP_STYLE}
        />
        <Bar dataKey="value" radius={[4, 4, 0, 0]} maxBarSize={48}>
          {data.map((datum, index) => (
            <Cell
              key={datum.label}
              fill={colorOf ? colorOf(index) : CHART.primary}
            />
          ))}
        </Bar>
      </RechartsBarChart>
    </ResponsiveContainer>
  );
}
