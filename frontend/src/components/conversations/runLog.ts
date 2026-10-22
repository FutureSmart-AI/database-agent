import { isPlainObject } from "lodash-es";

import type { Nl2sqlView } from "@/platform/components/conversations/nl2sql/normalizeNl2sql";

/**
 * What the run did in the background, read off a finished turn.
 *
 * The NL2SQL service emits no per-stage progress events — the stream is a run
 * of `data:` chunks and then one `full_metadata:` line — so this is a log read
 * after the fact rather than a live timeline. Every line is something the
 * service actually reported in `debug_info` (or in the block the transport
 * derives from it); nothing here is inferred from how long the UI waited.
 *
 * The strip above an answer says *what* came out of the run — SQL written,
 * tables read, rows returned. This says *how*: the question as the service
 * rewrote it, which database it picked, which tables it chose and why the
 * query touched them, the query itself, what running it returned, and what the
 * chart step decided.
 *
 * Two of the fields it is built from only exist on a live turn. `usage` — the
 * per-service latency, tokens and cost — rides the final stream event and is
 * not stored, so a thread read back later has the steps and their outcomes but
 * no cost. `partial` says which of the two this is, and the panel says so
 * rather than printing zeroes.
 */

export interface RunLogCall {
  service: string;
  latencyMs?: number;
  provider?: string;
  model?: string;
  inputTokens?: number;
  outputTokens?: number;
  costUsd?: number;
}

export type RunLogState = "done" | "failed" | "skipped" | "flagged";

export interface RunLogStep {
  key: string;
  label: string;
  /** One line summarising the step. */
  detail?: string;
  state: RunLogState;
  /** The step's own log lines, shown when it is unfolded. */
  lines?: string[];
  /** What this step cost, when the run reported it per service. */
  call?: RunLogCall;
}

export interface RunLog {
  steps: RunLogStep[];
  /** The run as a whole, when the turn reported timings or usage. */
  totals?: { latencyMs?: number; totalTokens?: number; costUsd?: number };
  /** The pipeline the service says it ran, e.g. `agentic_rag`. */
  runType?: string;
  /**
   * The run's trace id, when the turn carried one.
   *
   * It is the only handle that ties an answer in the thread to the run behind
   * it in the service's own logs, and it was the one field of the payload that
   * reached no surface at all.
   */
  traceId?: string;
  model?: string;
  /** A turn with no usage block: steps, but no tokens or cost. */
  partial: boolean;
  /** The ids this turn carries, for support and for the service's own logs. */
  ids?: { label: string; value: string }[];
}

const asObject = (value: unknown): Record<string, unknown> | null =>
  isPlainObject(value) ? (value as Record<string, unknown>) : null;

const num = (value: unknown): number | undefined => {
  const parsed = typeof value === "string" ? Number(value) : value;
  return typeof parsed === "number" && Number.isFinite(parsed)
    ? parsed
    : undefined;
};

const str = (value: unknown): string | undefined =>
  typeof value === "string" && value.trim() ? value : undefined;

export const formatMs = (ms: number): string =>
  ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${Math.round(ms)}ms`;

/** Cost to the cent is useless at these magnitudes — four places, or "<$0.0001". */
export const formatCost = (usd: number): string =>
  usd > 0 && usd < 0.0001 ? "<$0.0001" : `$${usd.toFixed(4)}`;

const callOf = (usage: Record<string, unknown> | null, service: string) => {
  const calls = usage?.service_calls;
  if (!Array.isArray(calls)) return undefined;
  const found = calls.find((entry) => asObject(entry)?.service === service) as
    Record<string, unknown> | undefined;
  if (!found) return undefined;
  return {
    service,
    latencyMs: num(found.latency_ms),
    provider: str(found.provider),
    model: str(found.model),
    inputTokens: num(found.input_tokens),
    outputTokens: num(found.output_tokens),
    costUsd: num(found.cost_usd),
  } satisfies RunLogCall;
};

/**
 * Steps the service narrated itself, when it narrated any.
 *
 * `debug_info.steps` is what the old "Steps" tab drew. It is the run's own
 * account of its plan, so it is logged verbatim between the question and the
 * query rather than being summarised away.
 */
function reportedSteps(debug: Record<string, unknown> | null): RunLogStep[] {
  const steps = debug?.steps;
  if (!Array.isArray(steps)) return [];
  return steps.flatMap((step, index): RunLogStep[] => {
    if (typeof step === "string") {
      return [{ key: `step-${index}`, label: step, state: "done" }];
    }
    const entry = asObject(step);
    if (!entry) return [];
    const label =
      str(entry.name) ?? str(entry.step) ?? str(entry.label) ?? str(entry.type);
    if (!label) return [];
    return [
      {
        key: `step-${index}`,
        label,
        detail:
          str(entry.detail) ?? str(entry.description) ?? str(entry.status),
        state: "done",
      },
    ];
  });
}

/**
 * Everything the chart block's `metadata` says, as log lines.
 *
 * The card can only use some of it — it draws the title, the axis labels and
 * its own palette. The rest (which column each axis was read from, whether a
 * legend was asked for, the colours the run proposed) is still something the
 * service said about this answer, so it is logged rather than dropped.
 */
function chartMetadataLines(metadata: unknown): string[] | undefined {
  const meta = asObject(metadata);
  if (!meta) return undefined;
  const axis = (key: "x_axis" | "y_axis", name: string): string[] => {
    const entry = asObject(meta[key]);
    if (!entry) return [];
    const label = str(entry.label);
    const field = str(entry.field);
    if (!label && !field) return [];
    return [`${name}: ${label ?? "—"}${field ? `  (column: ${field})` : ""}`];
  };
  const legend = asObject(meta.legend);
  const colors = Array.isArray(meta.colors) ? meta.colors : [];
  const lines = [
    ...(str(meta.title) ? [`title:  ${str(meta.title)}`] : []),
    ...axis("x_axis", "x"),
    ...axis("y_axis", "y"),
    ...(legend
      ? [
          `legend: ${legend.show === false ? "off" : "on"}${
            str(legend.position) ? ` (${str(legend.position)})` : ""
          }`,
        ]
      : []),
    ...(colors.length
      ? [
          `colors: ${colors.length} proposed — ${colors
            .filter((color): color is string => typeof color === "string")
            .join(", ")}`,
          "",
          "The card draws the product palette rather than these, so a result",
          "reads the same in both themes and beside every other chart.",
        ]
      : []),
  ];
  return lines.length ? lines : undefined;
}

/** First line of a SQL statement, collapsed for a one-line summary. */
const oneLine = (sql: string, limit = 60): string => {
  const flat = sql.replace(/\s+/g, " ").trim();
  return flat.length > limit ? `${flat.slice(0, limit - 1)}…` : flat;
};

export interface RunLogInput {
  /** The whole assistant message, as `useChatStream` hands it over. */
  message: unknown;
  /** The normalised NL2SQL block, when the turn carried one. */
  view: Nl2sqlView | null;
  /** Sanitised failure text, when the run reported one. */
  error?: string | null;
  /** Whether the generated query may be shown — see `deriveTrace`. */
  showQuery?: boolean;
  /** Whether the rows the query returned may be shown. */
  showResults?: boolean;
}

/** The log for one assistant turn, or null when the turn reported nothing. */
export function readRunLog({
  message,
  view,
  error,
  showQuery = true,
  showResults = true,
}: RunLogInput): RunLog | null {
  /**
   * An agent that shows neither its query nor its rows does not name its
   * schema here either. The log used to report the database it chose and the
   * tables it read whatever the settings said, which is the same disclosure by
   * a quieter route; the run is still accounted for, minus those facts.
   */
  const showSchema = showQuery || showResults;
  const root = asObject(message);
  // Live and stored turns both land here: the transport re-serialises the
  // stored `debug_info` into the same object the stream sends.
  const debug = asObject(root?.debug_info);
  if (!debug && !view && !error) return null;

  const usage = asObject(debug?.usage) ?? asObject(root?.usage);
  const steps: RunLogStep[] = [];

  // 1 — the question, as the service decided to ask it. `refine_query` is the
  // spelling the deployed service uses; `refined_query` is the documented one.
  const asked = str(debug?.query) ?? str(debug?.user_query);
  const refined = str(debug?.refined_query) ?? str(debug?.refine_query);
  if (asked || refined) {
    const rewritten = !!asked && !!refined && asked.trim() !== refined.trim();
    steps.push({
      key: "question",
      label: rewritten ? "Rewrote the question" : "Read the question",
      detail: refined ?? asked,
      state: "done",
      lines: rewritten
        ? [`asked:   ${asked}`, `used:    ${refined}`]
        : undefined,
    });
  }

  // 2 — whatever the run narrated about its own plan.
  steps.push(...reportedSteps(debug));

  // 3 — which database the question was routed to. An agent with one database
  // still reports it, and an agent with several is where this earns its line.
  const dbName = str(debug?.selected_db_name);
  const dbId = str(debug?.selected_db_id);
  if ((dbName || dbId) && showSchema) {
    steps.push({
      key: "database",
      label: "Chose the database",
      detail: dbName ?? dbId,
      state: "done",
      lines: dbName && dbId ? [`name: ${dbName}`, `id:   ${dbId}`] : undefined,
    });
  }

  // 4 — the tables. The service reports `selected_tables` when it schema-picks;
  // when it does not, the transport reads them off the query itself, and the
  // log says which of the two happened rather than passing one off as the other.
  const selected = Array.isArray(debug?.selected_tables)
    ? (debug.selected_tables as unknown[]).filter(
        (name): name is string => typeof name === "string",
      )
    : [];
  const tables = selected.length ? selected : (view?.tablesUsed ?? []);
  if (tables.length && showSchema) {
    steps.push({
      key: "tables",
      label: selected.length ? "Selected tables" : "Read tables",
      detail: `${tables.length === 1 ? "1 table" : `${tables.length} tables`} · ${tables.join(", ")}`,
      state: "done",
      lines: selected.length
        ? tables
        : [
            ...tables,
            "",
            "Read off the generated query — the run reported no" +
              " table selection of its own.",
          ],
    });
  }

  // 5 — the query itself, in full. An agent that does not show its query keeps
  // the step, so the log still accounts for the run, but not the SQL.
  if (view?.sqlQuery && !showQuery) {
    steps.push({
      key: "sql",
      label: "Wrote the query",
      detail: "not shown — this agent does not expose its SQL",
      state: "done",
      call: callOf(usage, "sql_generation"),
    });
  } else if (view?.sqlQuery) {
    steps.push({
      key: "sql",
      label: "Wrote the query",
      detail: oneLine(view.sqlQuery),
      state: "done",
      lines: view.sqlQuery.split("\n"),
      call: callOf(usage, "sql_generation"),
    });
  }

  // 6 — running it. A preview row count is labelled as one: "5 rows" over a
  // result that actually has five thousand is the kind of line an owner acts on.
  const latencyMs = num(debug?.latency_ms) ?? view?.executionTimeMs;
  const truncated = asObject(debug?.db_result)?.truncated === true;
  if (
    (view?.rowCount !== undefined && showResults) ||
    latencyMs !== undefined
  ) {
    const bits = [
      ...(view?.rowCount !== undefined && showResults
        ? [
            `${view.rowCount.toLocaleString()} ${view.rowCount === 1 ? "row" : "rows"}${
              view.rowCountIsPreview || truncated ? " shown" : ""
            }`,
          ]
        : []),
      ...(latencyMs !== undefined ? [formatMs(latencyMs)] : []),
    ];
    steps.push({
      key: "exec",
      label: "Ran the query",
      detail: bits.join(" · ") || undefined,
      state: "done",
      lines:
        view?.rowCountIsPreview || truncated
          ? [
              "The service returned a preview of the result. Export CSV or Full",
              "dataset reads every row the run staged.",
            ]
          : undefined,
    });
  }

  // 7 — the chart node, which runs whether or not it ends up drawing anything.
  // Its metadata is logged in full: the title, both axes with the columns they
  // were read from, whether a legend was asked for and how many colours the run
  // proposed. The card draws what it can use; nothing the service sent is lost.
  // Its absence is not evidence: only a turn that carried a chart block at all
  // gets the step, so an agent with charts switched off logs no chart line.
  const chartBlock =
    asObject(root?.chart_output) ?? asObject(root?.graph_output) ?? null;
  if (view?.chart || chartBlock) {
    const suggestion = view?.chart?.suggestion;
    const drew = Boolean(suggestion && view?.chart?.data);
    steps.push({
      key: "chart",
      label: drew
        ? `Built a ${suggestion}`
        : suggestion
          ? `Suggested a ${suggestion}`
          : "Decided against a chart",
      state: drew || suggestion ? "done" : "skipped",
      detail: drew ? undefined : "no chart data came back with the answer",
      lines: chartMetadataLines(view?.chart?.metadata),
      call: callOf(usage, "chart"),
    });
  }

  // 8 — the service's own verdict on the turn. `is_answered: false` means the
  // run finished and decided it had not answered; it is flagged rather than
  // failed, because there is an answer on screen to read.
  if (root?.is_answered === false) {
    steps.push({
      key: "answered",
      label: "Reported no answer",
      detail: "the service marked this turn is_answered: false",
      state: "flagged",
      lines: [
        "The run completed, but reported that it did not answer the",
        "question — the text above is what it produced anyway.",
      ],
    });
  }

  // 9 — a run that failed says so as its last line, in red.
  if (error) {
    steps.push({
      key: "failed",
      label: "Run failed",
      detail: error,
      state: "failed",
      lines: error.split("\n"),
    });
  }

  if (!steps.length) return null;

  const calls = Array.isArray(usage?.service_calls) ? usage.service_calls : [];
  const summed = calls.reduce(
    (sum: number, entry) => sum + (num(asObject(entry)?.latency_ms) ?? 0),
    0,
  );
  const cost = calls.reduce(
    (sum: number, entry) => sum + (num(asObject(entry)?.cost_usd) ?? 0),
    0,
  );
  const totals =
    usage || latencyMs !== undefined
      ? {
          latencyMs: summed || latencyMs,
          totalTokens: num(usage?.total_tokens),
          costUsd: cost || undefined,
        }
      : undefined;

  return {
    steps,
    totals,
    runType: str(debug?.type) ?? str(debug?.flow) ?? str(debug?.pipeline),
    traceId: str(root?.trace_id) ?? str(debug?.trace_id),
    // Every id the turn carries. A reader chasing an answer through the
    // service's logs needs the session and the turn, not only the trace.
    ids: [
      ...((str(root?.trace_id) ?? str(debug?.trace_id))
        ? [
            {
              label: "trace",
              value: (str(root?.trace_id) ?? str(debug?.trace_id))!,
            },
          ]
        : []),
      ...(str(root?.session_id)
        ? [{ label: "session", value: str(root?.session_id)! }]
        : []),
      ...(str(root?.chat_id)
        ? [{ label: "turn", value: str(root?.chat_id)! }]
        : []),
      ...(str(debug?.selected_db_id) && showSchema
        ? [{ label: "database", value: str(debug?.selected_db_id)! }]
        : []),
    ],
    model: callOf(usage, "sql_generation")?.model ?? str(debug?.model),
    // No usage block means the turn cannot report tokens or cost — every
    // deployed turn today, live or stored.
    partial: !usage,
  };
}
