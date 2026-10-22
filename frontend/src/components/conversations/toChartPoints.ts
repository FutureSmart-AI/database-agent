import type { Nl2sqlChartView } from "@/platform/components/conversations/nl2sql/normalizeNl2sql";

import { kindFromSuggestion, type ChartKind } from "./chartKinds";

export interface ChartPoint {
  label: string;
  value: number;
}

export interface ChartRender {
  /** The reading the service suggested — the card's opening view, not a cage. */
  kind: ChartKind;
  points: ChartPoint[];
  /** Axis labels the service supplied, for the meta chips. */
  xLabel?: string;
  yLabel?: string;
}

function asNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value.replace(/,/g, ""));
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

function label(value: unknown, index: number): string {
  if (value === null || value === undefined || value === "") {
    return String(index + 1);
  }
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

/**
 * Flattens the chart block into points the app's own chart components draw.
 *
 * `chart.data` arrives in the two shapes `ChartData["data"]` allows — a row
 * array of `{ x, y }` or a columnar `{ x: [...], y: [...] }`. Line and scatter
 * charts use the columnar form, so handling only the array silently drops them
 * (the same trap `ChartMetaPreview` documents). `graph_output.chart_data` names
 * its pairs `{ category, value }`, which is why both spellings are read.
 */
export function toChartPoints(
  chart: Nl2sqlChartView | undefined,
): ChartRender | null {
  if (!chart) return null;

  const metadata = chart.metadata as
    { x_axis?: { label?: string }; y_axis?: { label?: string } } | undefined;
  const xLabel = metadata?.x_axis?.label;
  const yLabel = metadata?.y_axis?.label;

  const kind = kindFromSuggestion(chart.suggestion);

  const points: ChartPoint[] = [];
  const data = chart.data;

  if (Array.isArray(data)) {
    data.forEach((row, index) => {
      if (!row || typeof row !== "object") return;
      const entry = row as Record<string, unknown>;
      const value = asNumber(entry.y ?? entry.value);
      if (value === null) return;
      points.push({
        label: label(
          entry.x ?? entry.label ?? entry.category ?? entry.index,
          index,
        ),
        value,
      });
    });
  } else if (data && typeof data === "object") {
    const columnar = data as { x?: unknown; y?: unknown };
    if (Array.isArray(columnar.x) && Array.isArray(columnar.y)) {
      columnar.x.forEach((x, index) => {
        const value = asNumber((columnar.y as unknown[])[index]);
        if (value === null) return;
        points.push({ label: label(x, index), value });
      });
    }
  }

  return points.length ? { kind, points, xLabel, yLabel } : null;
}
