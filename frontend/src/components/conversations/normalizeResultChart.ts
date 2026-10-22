import { SERIES } from "@/lib/colors";
import type { Nl2sqlChartView } from "@/platform/components/conversations/nl2sql/normalizeNl2sql";

import { toChartPoints, type ChartRender } from "./toChartPoints";

export interface StackedSeries {
  /** Generated key: source labels must not become property paths. */
  key: string;
  label: string;
  color: string;
}

export interface StackedRow {
  label: string;
  /** An absent series stays absent; it is not an observed zero. */
  values: Record<string, number>;
}

export interface StackedChart {
  rows: StackedRow[];
  series: StackedSeries[];
  orientation: "horizontal" | "vertical";
  mode: "normal" | "percent";
  showLegend: boolean;
  legendTitle?: string;
  xLabel?: string;
  yLabel?: string;
}

export type ResultChartView =
  | { shape: "flat"; chart: ChartRender }
  | { shape: "stacked"; chart: StackedChart }
  | { shape: "invalid"; reason: string };

const object = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value);
const text = (value: unknown) =>
  typeof value === "string" ? value : undefined;
const invalid = (reason: string): ResultChartView => ({
  shape: "invalid",
  reason,
});

/** Interpret the API shape once, without collapsing series or changing values. */
export function normalizeResultChart(
  source: Nl2sqlChartView | undefined,
): ResultChartView | null {
  if (!source) return null;
  const declaredStacked =
    source.suggestion?.trim().toLowerCase() === "stacked bar chart";
  const nested =
    Array.isArray(source.data) &&
    source.data.some((row) => object(row) && Object.hasOwn(row, "segments"));
  if (!declaredStacked && !nested) {
    const chart = toChartPoints(source);
    return chart ? { shape: "flat", chart } : null;
  }
  if (!declaredStacked)
    return invalid("The chart type does not match its segmented data.");
  if (!Array.isArray(source.data) || !source.data.length) {
    return invalid("The stacked chart has no category rows.");
  }

  const metadata = object(source.metadata) ? source.metadata : {};
  const orientation = metadata.chart_orientation ?? "horizontal";
  const mode = metadata.stack_type ?? "normal";
  if (orientation !== "horizontal" && orientation !== "vertical") {
    return invalid("The stacked chart has an unsupported orientation.");
  }
  if (mode !== "normal" && mode !== "percent") {
    return invalid("The chart's stacking mode is not supported.");
  }
  const colors = object(metadata.colors) ? metadata.colors : {};
  const legend = object(metadata.legend) ? metadata.legend : {};
  const series: StackedSeries[] = [];
  const byLabel = new Map<string, string>();
  const indices = new Set<string>();
  const rows: StackedRow[] = [];

  for (const row of source.data) {
    if (
      !object(row) ||
      typeof row.index !== "string" ||
      !Array.isArray(row.segments)
    ) {
      return invalid(
        "Each stacked category must have an index and a segment list.",
      );
    }
    if (indices.has(row.index))
      return invalid("Duplicate chart categories cannot be combined safely.");
    indices.add(row.index);
    const values: Record<string, number> = {};
    const categories = new Set<string>();
    let total = 0;
    for (const segment of row.segments) {
      if (
        !object(segment) ||
        typeof segment.category !== "string" ||
        typeof segment.value !== "number" ||
        !Number.isFinite(segment.value)
      ) {
        return invalid(
          "Each chart segment must have a category and a finite numeric value.",
        );
      }
      if (categories.has(segment.category)) {
        return invalid(
          "Duplicate series within a category cannot be combined safely.",
        );
      }
      categories.add(segment.category);
      if (mode === "percent" && segment.value < 0) {
        return invalid(
          "Percentage composition is undefined for negative segment values.",
        );
      }
      let key = byLabel.get(segment.category);
      if (key === undefined) {
        key = `series_${series.length}`;
        byLabel.set(segment.category, key);
        const supplied = colors[segment.category];
        const color =
          typeof supplied === "string" &&
          /^#(?:[\da-f]{3}|[\da-f]{4}|[\da-f]{6}|[\da-f]{8})$/i.test(supplied)
            ? supplied
            : SERIES[series.length % SERIES.length];
        series.push({ key, label: segment.category, color });
      }
      values[key] = segment.value;
      total += segment.value;
    }
    if (mode === "percent" && (!Number.isFinite(total) || total <= 0)) {
      return invalid(
        "Percentage composition requires a positive total for every category.",
      );
    }
    rows.push({ label: row.index, values });
  }
  if (!series.length)
    return invalid("The stacked chart has no segment values.");
  return {
    shape: "stacked",
    chart: {
      rows,
      series,
      orientation,
      mode,
      showLegend: legend.show !== false,
      legendTitle: text(legend.title),
      xLabel: object(metadata.x_axis) ? text(metadata.x_axis.label) : undefined,
      yLabel: object(metadata.y_axis) ? text(metadata.y_axis.label) : undefined,
    },
  };
}
