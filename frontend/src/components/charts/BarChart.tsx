"use client";

import {
  Bar,
  CartesianGrid,
  Cell,
  LabelList,
  BarChart as RechartsBarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { CHART, TOOLTIP_STYLE } from "@/lib/colors";
import { compact } from "@/lib/format";

import { LABEL_MAX_CHARS, ROW_HEIGHT } from "./constants";

export interface BarDatum {
  label: string;
  value: number;
}

interface BarChartProps {
  data: BarDatum[];
  title?: string;
}

const truncate = (label: string) =>
  label.length > LABEL_MAX_CHARS
    ? `${label.slice(0, LABEL_MAX_CHARS - 1)}…`
    : label;

/**
 * Horizontal bar chart, drawn with recharts and the agent UI's chart styling:
 * indigo bars, muted axis labels, no axis lines and the shared tooltip chrome.
 */
export default function BarChart({ data, title }: BarChartProps) {
  if (!data.length) return null;

  return (
    <ResponsiveContainer width="100%" height={data.length * ROW_HEIGHT + 16}>
      <RechartsBarChart
        data={data}
        layout="vertical"
        margin={{ top: 8, right: 56, left: 0, bottom: 8 }}
        aria-label={`${title || "Chart"} — horizontal bar chart, ${data.length} values`}
      >
        <CartesianGrid horizontal={false} stroke={CHART.grid} />
        <XAxis type="number" hide />
        <YAxis
          type="category"
          dataKey="label"
          width={160}
          stroke={CHART.axis}
          fontSize={11}
          tickLine={false}
          axisLine={false}
          tickFormatter={truncate}
        />
        <Tooltip
          cursor={{ fill: "#6366f10D" }}
          formatter={(value: number) => [compact(value), title ?? "Value"]}
          contentStyle={TOOLTIP_STYLE}
        />
        <Bar dataKey="value" radius={[0, 4, 4, 0]} barSize={20}>
          {data.map((datum) => (
            <Cell key={datum.label} fill={CHART.primary} />
          ))}
          <LabelList
            dataKey="value"
            position="right"
            formatter={(value: number) => compact(value)}
            style={{ fill: "#475569", fontSize: 11, fontWeight: 600 }}
          />
        </Bar>
      </RechartsBarChart>
    </ResponsiveContainer>
  );
}
