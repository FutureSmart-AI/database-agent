"use client";

import AreaChart from "@/components/charts/AreaChart";
import BarChart from "@/components/charts/BarChart";
import ColumnChart from "@/components/charts/ColumnChart";
import LineChart from "@/components/charts/LineChart";
import PointChart from "@/components/charts/PointChart";
import SharePie from "@/components/charts/SharePie";
import { CHART } from "@/lib/colors";

import type { ChartKind } from "./chartKinds";
import { CATEGORY_FILLS } from "./constants";
import type { ChartRender } from "./toChartPoints";

interface ResultChartProps {
  chart: ChartRender;
  kind: ChartKind;
  title: string;
}

/** Colour for the nth slice or bar of a categorical chart. */
export const categoryFill = (index: number): string =>
  CATEGORY_FILLS[index % CATEGORY_FILLS.length];

/** One result, drawn the way the reader asked for it. */
export default function ResultChart({ chart, kind, title }: ResultChartProps) {
  const { points, xLabel, yLabel } = chart;

  switch (kind) {
    case "column":
      return <ColumnChart data={points} title={title} />;

    case "line":
      return (
        <LineChart
          series={[
            {
              values: points.map((point) => point.value),
              color: CHART.primary,
              name: yLabel ?? "Value",
            },
          ]}
          label={`${title} — line chart, ${points.length} points`}
          ticks={points.map((point) => point.label)}
        />
      );

    case "area":
      return <AreaChart data={points} title={title} />;

    case "pie":
    case "donut":
      return (
        <SharePie
          data={points}
          title={title}
          donut={kind === "donut"}
          colorOf={categoryFill}
        />
      );

    case "scatter":
      return <PointChart data={points} title={title} xLabel={xLabel} />;

    case "bar":
    default:
      return <BarChart data={points} title={title} />;
  }
}
