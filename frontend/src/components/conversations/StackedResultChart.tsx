"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  LabelList,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { CHART, TOOLTIP_STYLE } from "@/lib/colors";

import type { StackedChart } from "./normalizeResultChart";

const numeric = (value: unknown) =>
  typeof value === "number" && Number.isFinite(value) ? String(value) : "";

/** A real series per segment category, with missing values distinct from zero. */
export default function StackedResultChart({
  chart,
  title,
}: {
  chart: StackedChart;
  title: string;
}) {
  const horizontal = chart.orientation === "horizontal";
  const percent = chart.mode === "percent";
  const data = chart.rows.map((row) => ({ label: row.label, ...row.values }));
  const ticks = (value: unknown) =>
    percent && typeof value === "number"
      ? `${Math.round(value * 100)}%`
      : numeric(value);
  const height = horizontal ? Math.max(220, chart.rows.length * 34 + 48) : 320;

  return (
    <figure className="m-0 min-w-0" aria-label={`${title} — stacked bar chart`}>
      {chart.showLegend && (
        <div
          className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-n2s-ink-2"
          aria-label="Chart series"
        >
          {chart.legendTitle && (
            <span className="font-semibold">{chart.legendTitle}</span>
          )}
          {chart.series.map((series) => (
            <span key={series.key} className="inline-flex items-center gap-1.5">
              <span
                className="inline-block size-2.5 rounded-sm"
                style={{ backgroundColor: series.color }}
              />
              {series.label}
            </span>
          ))}
        </div>
      )}
      {percent && (
        <p className="m-0 mb-2 text-[11px] text-n2s-ink-3">
          Percentage composition; tooltips show the original values.
        </p>
      )}
      <ResponsiveContainer width="100%" height={height}>
        <BarChart
          data={data}
          layout={horizontal ? "vertical" : "horizontal"}
          stackOffset={percent ? "expand" : "sign"}
          margin={{ top: 12, right: 24, left: 4, bottom: 24 }}
          aria-label={`${title} — ${chart.rows.length} categories, ${chart.series.length} series`}
        >
          <CartesianGrid
            stroke={CHART.grid}
            horizontal={!horizontal}
            vertical={horizontal}
          />
          {horizontal ? (
            <>
              <XAxis
                type="number"
                domain={percent ? [0, 1] : ["auto", "auto"]}
                tickFormatter={ticks}
                stroke={CHART.axis}
                fontSize={11}
              />
              <YAxis
                type="category"
                dataKey="label"
                width={150}
                interval={0}
                stroke={CHART.axis}
                fontSize={11}
              />
              <ReferenceLine x={0} stroke={CHART.axis} />
            </>
          ) : (
            <>
              <XAxis
                type="category"
                dataKey="label"
                interval={0}
                stroke={CHART.axis}
                fontSize={11}
              />
              <YAxis
                type="number"
                domain={percent ? [0, 1] : ["auto", "auto"]}
                tickFormatter={ticks}
                stroke={CHART.axis}
                fontSize={11}
              />
              <ReferenceLine y={0} stroke={CHART.axis} />
            </>
          )}
          <Tooltip formatter={numeric} contentStyle={TOOLTIP_STYLE} />
          {chart.series.map((series) => (
            <Bar
              key={series.key}
              name={series.label}
              dataKey={series.key}
              stackId="segments"
              fill={series.color}
              isAnimationActive={false}
            >
              <LabelList
                dataKey={series.key}
                position="center"
                formatter={numeric}
                style={{ fill: "#fff", fontSize: 11 }}
              />
            </Bar>
          ))}
        </BarChart>
      </ResponsiveContainer>
      <table className="sr-only">
        <caption>{title} — original segment values</caption>
        <thead>
          <tr>
            <th scope="col">{chart.xLabel ?? "Category"}</th>
            {chart.series.map((series) => (
              <th scope="col" key={series.key}>
                {series.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {chart.rows.map((row) => (
            <tr key={row.label}>
              <th scope="row">{row.label}</th>
              {chart.series.map((series) => (
                <td key={series.key}>
                  {Object.hasOwn(row.values, series.key)
                    ? numeric(row.values[series.key])
                    : "Not provided"}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}
