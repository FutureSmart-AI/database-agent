/**
 * Palette shared by every chart and status accent in this app.
 *
 * The values are the design artifact's own: the four categorical series, the
 * ordinal ramp, and the grid and axis chrome. They are not hand-picked — each
 * was run through the dataviz validator (OKLab CVD ΔE, lightness band, chroma
 * floor, WCAG contrast) against the artifact's surfaces. One standing
 * constraint comes with them: blue and amber measure ΔE 35.4 apart and are safe
 * together, but the success green and the failure red are not — they collapse
 * under deuteranopia — so pass/fail is never two touching fills, only a badge
 * carrying an icon and a label.
 *
 * Text, surface and border colours are not listed: those are Tailwind
 * utilities (`text-slate-500`, `border-slate-200`, …) which `styles/theme.css`
 * re-points at the same artifact ramp inside the product's `n2s-root` scope.
 */
export const CHART = {
  /** Primary series — FutureSmart blue. */
  primary: "#2563eb",
  /** Second series. Safe beside the primary for colour-blind readers. */
  amber: "#b87c15",
  /** Positive / success series. */
  emerald: "#1d7a4e",
  /** Fourth series. */
  violet: "#7c3aed",
  /** Negative series. */
  rose: "#b91c1c",
  /** Comparison period and de-emphasised marks — the lightest ordinal step. */
  muted: "#98b6ef",
  /** Gridlines. */
  grid: "#e8edf5",
  /** Axis rules and labels. */
  axis: "#6b7280",
} as const;

/** Categorical series in draw order, for charts that colour by index. */
export const SERIES = [
  CHART.primary,
  CHART.amber,
  CHART.emerald,
  CHART.violet,
] as const;

/**
 * Sequential ramp, for a single measure split into ordered buckets — where the
 * categorical series above would imply four unrelated things.
 */
export const ORDINAL = [
  "#98b6ef",
  "#6e97e7",
  "#4674d6",
  "#2854b4",
  "#173b82",
] as const;

/** Recharts tooltip chrome, on the artifact's card surface and hairline. */
export const TOOLTIP_STYLE = {
  backgroundColor: "var(--n2s-card, #ffffff)",
  border: "1px solid var(--n2s-line, #e3e9f2)",
  borderRadius: "10px",
  padding: "8px 12px",
  fontSize: "12px",
  boxShadow: "0 12px 32px -12px rgba(17, 24, 39, 0.22)",
} as const;
