import { ORDINAL, SERIES } from "@/lib/colors";

import { CHART_KINDS, type ChartKind } from "./chartKinds";

export const QUESTION_BUBBLE =
  "w-fit max-w-full rounded-2xl rounded-tr-md bg-linear-to-br from-indigo-600 via-blue-600 to-indigo-700 px-5 py-4 text-white shadow-lg";
export const ANSWER_BUBBLE =
  "min-w-0 flex-1 rounded-2xl rounded-tl-md border border-slate-200/80 bg-white shadow-md";
export const AVATAR =
  "flex size-10 shrink-0 items-center justify-center rounded-full bg-linear-to-br from-indigo-100 to-purple-100 text-indigo-700 shadow-md ring-2 ring-indigo-200/50";

/** Rows per page in an answer's result table, as in the design artifact. */
export const RESULT_PAGE_SIZE = 5;

/** Run-trace dot, by stage state. */
export const TRACE_DOT = {
  active: "bg-n2s-pri-wash text-n2s-pri",
  done: "bg-n2s-ok-wash text-n2s-ok",
  failed: "bg-n2s-err-wash text-n2s-err",
} as const;

/**
 * The three dots trailing a stage that is still running.
 *
 * A run can sit on "Thinking" for half a minute before the first chunk lands,
 * and a tick with a static label reads as a finished step that has stalled.
 * The wave is the one thing on screen that keeps saying the run is alive; the
 * classes are in `styles/theme.css`, so the delay stagger lives with the
 * keyframe.
 */
export const THINKING_DOTS = [
  "n2s-thinking-dot",
  "n2s-thinking-dot n2s-thinking-dot-2",
  "n2s-thinking-dot n2s-thinking-dot-3",
] as const;

/**
 * Run-trace label, by stage state.
 *
 * A running stage takes its colour from the shimmer's clipped gradient rather
 * than a text utility — see `n2s-shimmer-text` in `styles/theme.css`. It also sets
 * its own size rather than taking the row's: it is the one line the reader is
 * waiting on, so it sits a step above the settled rows around it.
 */
export const TRACE_LABEL = {
  active: "text-[14px] font-semibold n2s-shimmer-text",
  done: "font-medium text-n2s-ink-2",
  failed: "font-semibold text-n2s-err",
} as const;

/** Full-logs step dot, by what the step did. */
export const LOG_DOT = {
  done: "bg-n2s-ok-wash text-n2s-ok",
  failed: "bg-n2s-err-wash text-n2s-err",
  skipped: "bg-n2s-card-3 text-n2s-ink-3",
  flagged: "bg-n2s-amber-wash text-n2s-amber",
} as const;

/** Full-logs step label, by what the step did. */
export const LOG_LABEL = {
  done: "font-medium text-n2s-ink-2",
  failed: "font-semibold text-n2s-err",
  skipped: "font-medium text-n2s-ink-3",
  flagged: "font-medium text-n2s-ink-2",
} as const;

/** Chart-kind name, for the strip that says which reading is on screen. */
export const KIND_LABEL: Record<ChartKind, string> = Object.fromEntries(
  CHART_KINDS.map((option) => [option.key, option.label]),
) as Record<ChartKind, string>;

/**
 * Fills for a categorical chart, in draw order.
 *
 * The four validated series first, then the ordinal ramp: nine distinct fills
 * before anything repeats, and a repeat lands nine slices away rather than
 * beside itself. Nothing new is mixed here, so the CVD and contrast checks run
 * on `lib/colors` still hold.
 */
export const CATEGORY_FILLS = [...SERIES, ...ORDINAL];

/**
 * Declared column types whose values are numbers.
 *
 * `db_result.columns[].type` is the service's own word for the column; the
 * table right-aligns and numerically sorts the ones this matches rather than
 * judging the column by the sample of values that happened to come back.
 */
export const NUMERIC_COLUMN_TYPE =
  /^(int|bigint|smallint|integer|float|double|decimal|numeric|real|number|money)/i;
