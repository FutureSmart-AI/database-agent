"use client";

import {
  CartesianGrid,
  Line,
  LineChart as RechartsLineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { CHART, TOOLTIP_STYLE } from "@/lib/colors";
import { compact } from "@/lib/format";

export interface LineSeries {
  values: number[];
  color: string;
  /** Dashed lines carry the previous period. */
  dashed?: boolean;
  /** Series name in the tooltip. */
  name?: string;
}

interface LineChartProps {
  series: LineSeries[];
  label: string;
  height?: number;
  /** Category labels for the x axis; the axis is hidden when omitted. */
  ticks?: string[];
}

/**
 * Trend line chart in the agent UI's chart styling: 2px strokes for the current
 * period, a thinner dashed stroke for the comparison one, dotted gridlines and
 * the shared tooltip chrome.
 */
export default function LineChart({
  series,
  label,
  height = 140,
  ticks,
}: LineChartProps) {
  const points = Math.max(...series.map((s) => s.values.length), 1);
  const rows = Array.from({ length: points }, (_, index) => {
    const row: Record<string, number | string> = {
      tick: ticks?.[index] ?? String(index + 1),
    };
    series.forEach((entry, seriesIndex) => {
      row[`s${seriesIndex}`] = entry.values[index];
    });
    return row;
  });

  return (
    <ResponsiveContainer width="100%" height={height}>
      <RechartsLineChart
        data={rows}
        margin={{ top: 10, right: 12, left: 0, bottom: 4 }}
        aria-label={label}
      >
        <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} />
        <XAxis
          dataKey="tick"
          hide={!ticks}
          stroke={CHART.axis}
          fontSize={11}
          tickLine={false}
          axisLine={false}
        />
        <YAxis
          stroke={CHART.axis}
          fontSize={11}
          // Recharts' default gutter: a narrower one clips six-figure token
          // labels ("370.0K") instead of shrinking them.
          width={60}
          tickLine={false}
          axisLine={false}
          tickFormatter={(value: number) => compact(value)}
        />
        <Tooltip
          formatter={(value: number, name: string) => [compact(value), name]}
          contentStyle={TOOLTIP_STYLE}
        />
        {series.map((entry, index) => (
          <Line
            key={index}
            type="monotone"
            dataKey={`s${index}`}
            name={entry.name ?? (entry.dashed ? "Previous" : label)}
            stroke={entry.color}
            strokeWidth={entry.dashed ? 1.5 : 2}
            strokeDasharray={entry.dashed ? "5 3" : undefined}
            dot={false}
            activeDot={entry.dashed ? false : { r: 4 }}
          />
        ))}
      </RechartsLineChart>
    </ResponsiveContainer>
  );
}
