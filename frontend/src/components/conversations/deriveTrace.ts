import type { Nl2sqlView } from "@/platform/components/conversations/nl2sql/normalizeNl2sql";

/**
 * The run trace under an answer.
 *
 * Every row is backed by something the stream actually reported. The design
 * artifact shows five timed stages ticking through a run, but the NL2SQL SSE
 * stream carries only `chunk` / `response` / `debug_info` / `data` / `follow_up`
 * / `chat_id` / `error` — there are no progress events to drive them, and a
 * timer would only be theatre that a slow or fast run immediately contradicts.
 * So: two live rows the stream does evidence, then one completed row per fact
 * the finished run produced.
 */
export type TraceState = "active" | "done" | "failed";

export interface TraceRow {
  key: string;
  label: string;
  /** Monospace detail shown after the label; omitted when there is none. */
  detail?: string;
  state: TraceState;
}

export interface TraceInput {
  /** Whether the run is still streaming. */
  loading: boolean;
  /** The answer text so far — empty until the first chunk lands. */
  answer: string;
  /** Parsed NL2SQL block, once the run reports one. */
  view: Nl2sqlView | null;
  /** Sanitised failure text, when the run reported one. */
  error?: string | null;
  /**
   * Whether the generated query may be shown at all.
   *
   * The agent's "Show sources" settings hid the SQL from the result card but
   * not from this strip, which printed the first sixty characters of it under
   * every answer — so an agent configured never to show its query showed it
   * anyway, one line higher.
   */
  showQuery?: boolean;
}

/** First line of a SQL statement, collapsed for a one-line summary. */
export function sqlSummary(sql: string, limit = 60): string {
  const flat = sql.replace(/\s+/g, " ").trim();
  return flat.length > limit ? `${flat.slice(0, limit - 1)}…` : flat;
}

function formatMs(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${Math.round(ms)}ms`;
}

export function deriveTrace(input: TraceInput): TraceRow[] {
  const { loading, answer, view, error, showQuery = true } = input;

  if (loading) {
    const writing = answer.trim().length > 0;
    return [
      {
        key: "thinking",
        label: "Thinking",
        state: writing ? "done" : "active",
      },
      ...(writing
        ? [
            {
              key: "writing",
              label: "Writing the answer",
              state: "active" as const,
            },
          ]
        : []),
    ];
  }

  if (error) {
    return [
      { key: "thinking", label: "Thinking", state: "done" },
      { key: "failed", label: "Run failed", detail: error, state: "failed" },
    ];
  }

  // A finished run with no NL2SQL block answered from the model alone — there
  // is no query, no table and no row count to report, so there is no trace.
  if (!view) return [];

  const rows: TraceRow[] = [];
  if (view.sqlQuery && showQuery) {
    rows.push({
      key: "sql",
      label: "Generated SQL",
      detail: sqlSummary(view.sqlQuery),
      state: "done",
    });
  }
  if (view.tablesUsed.length) {
    rows.push({
      key: "tables",
      label: view.tablesUsed.length === 1 ? "Read table" : "Read tables",
      detail: view.tablesUsed.join(", "),
      state: "done",
    });
  }
  if (view.executionTimeMs !== undefined) {
    rows.push({
      key: "exec",
      label: "Executed",
      detail: formatMs(view.executionTimeMs),
      state: "done",
    });
  }
  if (view.rowCount !== undefined) {
    rows.push({
      key: "rows",
      label:
        view.rowCount === 1
          ? "Returned 1 row"
          : `Returned ${view.rowCount.toLocaleString()} rows`,
      detail: view.rowCountIsPreview ? "preview" : undefined,
      state: "done",
    });
  }
  return rows;
}
