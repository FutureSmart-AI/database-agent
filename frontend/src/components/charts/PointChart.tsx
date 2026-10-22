"use client";

import {
  CartesianGrid,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";

import { CHART, TOOLTIP_STYLE } from "@/lib/colors";
import { compact } from "@/lib/format";

import type { BarDatum } from "./BarChart";
import { CATEGORY_HEIGHT } from "./constants";

interface PointChartProps {
  data: BarDatum[];
  title?: string;
  xLabel?: string;
}

interface PointDatum extends BarDatum {
  index: number;
}

/**
 * Value per row as points rather than bars.
 *
 * Where bars read as "how much", a scatter reads as "how spread out": a
 * hundred rows that make an unreadable hedge of bars are still a legible cloud
 * here, which is the case this view is offered for.
 *
 * The category axis is numeric — the row's position — because recharts' own
 * category scale spaces ticks evenly and turns a scatter back into a bar chart
 * without the bars. The category name is not lost: the tooltip carries it,
 * which is why this draws its own rather than using the default two-row one.
 */
export default function PointChart({ data, title, xLabel }: PointChartProps) {
  if (!data.length) return null;

  const points: PointDatum[] = data.map((datum, index) => ({
    ...datum,
    index: index + 1,
  }));

  return (
    <ResponsiveContainer width="100%" height={CATEGORY_HEIGHT}>
      <ScatterChart
        margin={{ top: 12, right: 16, left: 0, bottom: 8 }}
        aria-label={`${title || "Chart"} — scatter chart, ${data.length} points`}
      >
        <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} />
        <XAxis
          type="number"
          dataKey="index"
          name={xLabel ?? "Row"}
          domain={[0, data.length + 1]}
          stroke={CHART.axis}
          fontSize={11}
          tickLine={false}
          axisLine={false}
          allowDecimals={false}
        />
        <YAxis
          type="number"
          dataKey="value"
          name={title ?? "Value"}
          stroke={CHART.axis}
          fontSize={11}
          width={60}
          tickLine={false}
          axisLine={false}
          tickFormatter={compact}
        />
        <ZAxis range={[48, 48]} />
        <Tooltip
          cursor={{ strokeDasharray: "3 3" }}
          content={({ payload }) => {
            const datum = payload?.[0]?.payload as PointDatum | undefined;
            if (!datum) return null;
            return (
              <div style={TOOLTIP_STYLE}>
                <div className="font-semibold text-n2s-ink">{datum.label}</div>
                <div className="text-n2s-ink-2">{compact(datum.value)}</div>
              </div>
            );
          }}
        />
        <Scatter
          data={points}
          fill={CHART.primary}
          fillOpacity={0.85}
          name={title ?? "Value"}
          isAnimationActive={false}
        />
      </ScatterChart>
    </ResponsiveContainer>
  );
}
