"use client";

import {
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
} from "recharts";

import { TOOLTIP_STYLE } from "@/lib/colors";
import { compact } from "@/lib/format";

import type { BarDatum } from "./BarChart";
import { CATEGORY_HEIGHT, PIE_LEGEND_MAX } from "./constants";

interface SharePieProps {
  data: BarDatum[];
  title?: string;
  /** A hole in the middle turns the same chart into a donut. */
  donut?: boolean;
  colorOf: (index: number) => string;
}

/**
 * One measure split by category, as a share of the whole.
 *
 * Separate from the dashboard's 80px `Donut`, which draws a fixed breakdown
 * with a figure in its hole. This one is the reader's own choice of view over
 * whatever a result returned, so it is responsive, legended and labelled by
 * category rather than sized and centred for a table cell.
 *
 * The slice values are the result's own — nothing is grouped into an "Other"
 * slice here, because a chart that quietly rewrites the rows behind it is
 * worse than a busy one. Past `PIE_LEGEND_MAX` categories the legend is
 * dropped (it would take the whole card) and the tooltip carries the names.
 */
export default function SharePie({
  data,
  title,
  donut = false,
  colorOf,
}: SharePieProps) {
  if (!data.length) return null;

  const total = data.reduce((sum, datum) => sum + datum.value, 0);
  const legend = data.length <= PIE_LEGEND_MAX;

  return (
    <ResponsiveContainer width="100%" height={CATEGORY_HEIGHT}>
      <PieChart
        aria-label={`${title || "Chart"} — ${donut ? "donut" : "pie"} chart, ${data.length} slices`}
      >
        <Pie
          data={data}
          dataKey="value"
          nameKey="label"
          cx="50%"
          cy="50%"
          innerRadius={donut ? "48%" : 0}
          outerRadius="78%"
          paddingAngle={data.length > 1 ? 1 : 0}
          stroke="var(--n2s-card, #ffffff)"
          strokeWidth={1}
          isAnimationActive={false}
        >
          {data.map((datum, index) => (
            <Cell key={`${datum.label}-${index}`} fill={colorOf(index)} />
          ))}
        </Pie>
        <Tooltip
          contentStyle={TOOLTIP_STYLE}
          formatter={(value: number, name: string) => [
            total > 0
              ? `${compact(value)} · ${((value / total) * 100).toFixed(1)}%`
              : compact(value),
            name,
          ]}
        />
        {legend && (
          <Legend
            verticalAlign="middle"
            align="right"
            layout="vertical"
            iconType="circle"
            iconSize={8}
            wrapperStyle={{ fontSize: 11, paddingLeft: 12 }}
          />
        )}
      </PieChart>
    </ResponsiveContainer>
  );
}
