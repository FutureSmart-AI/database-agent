"use client";

import {
  Bar,
  BarChart,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { CHART_INITIAL_DIMENSION } from "@/platform/analytics/constants";

/**
 * Horizontal bars for a failure breakdown, matching `CostByNodeChart`'s
 * geometry and palette so the Failures tab reads as the same page as the rest.
 */
const BAR_COLORS = [
  "#ef4444",
  "#f59e0b",
  "#ec4899",
  "#8b5cf6",
  "#6366f1",
  "#06b6d4",
  "#10b981",
  "#84cc16",
];

export default function FailureBreakdownChart({
  data,
  onSelect,
  selected,
}: {
  data: { label: string; count: number }[];
  onSelect?: (label: string) => void;
  selected?: string | null;
}) {
  return (
    <ResponsiveContainer
      width="100%"
      height="100%"
      initialDimension={CHART_INITIAL_DIMENSION}
    >
      <BarChart
        layout="vertical"
        data={data}
        margin={{ top: 4, right: 16, left: 8, bottom: 4 }}
      >
        <XAxis
          type="number"
          stroke="#666"
          fontSize={12}
          tickLine={false}
          axisLine={false}
          allowDecimals={false}
        />
        <YAxis
          type="category"
          dataKey="label"
          stroke="#666"
          fontSize={12}
          tickLine={false}
          axisLine={false}
          width={112}
        />
        <Tooltip
          cursor={{ fill: "#ef44440D" }}
          formatter={(v: number) => [`${v}`, "Failures"]}
          contentStyle={{
            backgroundColor: "white",
            border: "1px solid #e5e7eb",
            borderRadius: "6px",
            padding: "8px 12px",
          }}
        />
        <Bar
          dataKey="count"
          radius={[0, 4, 4, 0]}
          // recharts hands the bar rectangle, whose `payload` is the row we
          // passed in; it types that as unknown-shaped, hence the narrow cast.
          onClick={(bar) => {
            const label = (bar as { payload?: { label?: string } })?.payload
              ?.label;
            if (label) onSelect?.(label);
          }}
          cursor={onSelect ? "pointer" : undefined}
        >
          {data.map((row, i) => (
            <Cell
              key={row.label}
              fill={BAR_COLORS[i % BAR_COLORS.length]}
              fillOpacity={selected && selected !== row.label ? 0.3 : 1}
            />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
