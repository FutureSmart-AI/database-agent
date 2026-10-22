import type { IconName } from "@/components/Icon";

import type { ChartPoint } from "./toChartPoints";

/**
 * The readings a result can be drawn as.
 *
 * The service suggests one — "Bar Chart", "Line Chart" — and that suggestion
 * decides what the card opens on. It is a suggestion, though: the model picked
 * it from the question, not from the shape of the rows that came back, and the
 * reader is the one looking at them. So every kind the data supports is
 * offered, and the pick is theirs.
 */
export type ChartKind =
  "bar" | "column" | "line" | "area" | "pie" | "donut" | "scatter";

export interface ChartKindOption {
  key: ChartKind;
  /** Name in the picker's tooltip and accessible label. */
  label: string;
  icon: IconName;
}

/** Picker order: the two bar readings, the two trend readings, then shares. */
export const CHART_KINDS: readonly ChartKindOption[] = [
  { key: "bar", label: "Bar", icon: "barsH" },
  { key: "column", label: "Column", icon: "barsV" },
  { key: "line", label: "Line", icon: "lineUp" },
  { key: "area", label: "Area", icon: "areaUp" },
  { key: "pie", label: "Pie", icon: "pie" },
  { key: "donut", label: "Donut", icon: "donut" },
  { key: "scatter", label: "Scatter", icon: "points" },
] as const;

/**
 * The kind the service's own suggestion names.
 *
 * Matched longest-meaning-first: "donut" before "pie" (a donut suggestion
 * contains neither, but a "pie/donut" one contains both), and the vertical
 * spellings before the bare "bar", which is this product's horizontal default.
 */
export function kindFromSuggestion(suggestion: string | undefined): ChartKind {
  const text = (suggestion ?? "").toLowerCase();
  if (/donut|doughnut/.test(text)) return "donut";
  if (/pie/.test(text)) return "pie";
  // Not a bare "point": a suggestion reads "pie chart of the data points"
  // often enough that matching it turned pies into scatters.
  if (/scatter|bubble/.test(text)) return "scatter";
  if (/area/.test(text)) return "area";
  if (/line|trend|time|series/.test(text)) return "line";
  if (/column|vertical/.test(text)) return "column";
  return "bar";
}

/**
 * Why a kind cannot draw this result, or null when it can.
 *
 * Only one rule so far, and it is arithmetic rather than taste: a share of the
 * whole is meaningless when a part is negative — recharts draws the slice
 * anyway, at a size that says the opposite of what the number does.
 */
export function unavailableReason(
  kind: ChartKind,
  points: ChartPoint[],
): string | null {
  if ((kind === "pie" || kind === "donut") && points.some((p) => p.value < 0)) {
    return "A share of the whole cannot show negative values";
  }
  return null;
}

/** The kinds this result can actually be drawn as. */
export const availableKinds = (points: ChartPoint[]): ChartKindOption[] =>
  CHART_KINDS.filter((option) => !unavailableReason(option.key, points));
