"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import Icon, { type IconName } from "@/components/Icon";
import { copyText } from "@/lib/clipboard";
import { highlightSql } from "@/lib/sql";
import { fetchDatasetRows } from "@/platform/components/conversations/nl2sql/fetchDatasetRows";
import FullDatasetModal from "@/platform/components/conversations/nl2sql/FullDatasetModal";
import type { Nl2sqlView } from "@/platform/components/conversations/nl2sql/normalizeNl2sql";
import { downloadCsv } from "@/platform/components/conversations/nl2sql/rowsToCsv";
import { isSafeHttpUrl } from "@/platform/components/conversations/nl2sql/urlSafety";

import { availableKinds, type ChartKind } from "./chartKinds";
import { KIND_LABEL } from "./constants";
import { normalizeResultChart } from "./normalizeResultChart";
import ResultChart from "./ResultChart";
import ResultTable, { display } from "./ResultTable";
import StackedResultChart from "./StackedResultChart";

type TabKey = "chart" | "data" | "query" | "raw";

interface ResultCardProps {
  view: Nl2sqlView;
  /** The whole assistant message, dumped verbatim under Raw. */
  raw?: unknown;
  /** Whether the generated query may be shown. */
  showQuery?: boolean;
  /** Whether the returned rows and the chart may be shown. */
  showResults?: boolean;
  /** Whether the agent exposes the untouched API payload. */
  rawEnabled?: boolean;
}

/**
 * Columns the artifact folds away on arrival: the row's own key and the
 * timestamp of its last write, which push the columns a reader came for off
 * the edge of the card. Nothing is dropped — the Columns menu carries them,
 * the export carries them, and the button says how many are folded.
 */
function defaultHidden(columns: string[]): Record<string, boolean> {
  const noisy = columns.filter(
    (key) => key === "id" || key === "updated_at" || key.endsWith("_id"),
  );
  // Never fold everything away: a card with one column left reads as broken.
  if (!noisy.length || noisy.length >= columns.length) return {};
  return Object.fromEntries(noisy.map((key) => [key, true]));
}

/**
 * Everything one answer produced, behind one strip of tabs.
 *
 * The chart, the rows it was drawn from, the query that fetched them and the
 * untouched payload are four readings of a single run, so they sit in a single
 * card and cost one click each — rather than a result card stacked on a
 * separate collapsible "How I got this" panel, which spent two boxes, two bars
 * of chrome and a scroll on what is one answer. The tab strip carries the
 * active view's own controls on its right, so a result is one bar of chrome
 * tall whichever tab is open.
 *
 * The export is deliberately not reimplemented: `downloadCsv`,
 * `fetchDatasetRows` and `isSafeHttpUrl` are the agent UI's own, so the rule
 * that Export CSV downloads the *full* staged result rather than the preview
 * page — and relabels itself when S3 cannot be reached — cannot drift here.
 */
export default function ResultCard({
  view,
  raw,
  showQuery = false,
  showResults = true,
  rawEnabled = false,
}: ResultCardProps) {
  const rows = useMemo(
    () => (showResults ? (view.previewRows ?? []) : []),
    [view.previewRows, showResults],
  );
  const resultChart = useMemo(
    () => (showResults ? normalizeResultChart(view.chart) : null),
    [view.chart, showResults],
  );
  const chart = resultChart?.shape === "flat" ? resultChart.chart : null;
  const chartAxes =
    resultChart?.shape === "stacked" ? resultChart.chart : chart;
  const sql = showQuery ? view.sqlQuery : undefined;

  /**
   * What the service called this chart.
   *
   * `chart_data.metadata.title` is the run's own title for the result
   * ("Missing Logs for Active Members (Last Week)"). Until now the card threw
   * it away and titled every chart after its *type*, so each one announced
   * itself to a screen reader as "Bar Chart — horizontal bar chart".
   */
  const chartTitle =
    (view.chart?.metadata as { title?: string } | undefined)?.title ??
    view.chart?.suggestion ??
    "Result";

  // Null until a tab is picked, so the card can resolve its own opening view
  // from what the run actually produced.
  const [tab, setTab] = useState<TabKey | null>(null);
  const [query, setQuery] = useState("");
  const [hidden, setHidden] = useState<Record<string, boolean>>({});
  const [columnsOpen, setColumnsOpen] = useState(false);
  const [datasetOpen, setDatasetOpen] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [fullExportFailed, setFullExportFailed] = useState(false);
  const [copied, setCopied] = useState(false);
  // Null until the reader picks one, so the chart opens on what the service
  // suggested and only stops following it once they say otherwise.
  const [chartKind, setChartKind] = useState<ChartKind | null>(null);
  const columnsRef = useRef<HTMLDivElement>(null);

  /**
   * Every column across every row, in the order the service declared.
   *
   * `db_result.columns` states the order the query selected in; the rows state
   * only whatever key order the JSON happened to carry. A declared column with
   * no key in any row is still dropped — it would draw a column of blanks —
   * and a key no column declared is kept, at the end.
   */
  const allColumns = useMemo(() => {
    const keys = new Set<string>();
    for (const row of rows) for (const key of Object.keys(row)) keys.add(key);
    const declared = (view.columns ?? [])
      .map((column) => column.name)
      .filter((name) => keys.has(name));
    return [...declared, ...[...keys].filter((key) => !declared.includes(key))];
  }, [rows, view.columns]);

  /** The type the service declared for each column, for the table's header. */
  const columnTypes = useMemo(
    () =>
      Object.fromEntries(
        (view.columns ?? []).flatMap((column) =>
          column.type ? [[column.name, column.type]] : [],
        ),
      ) as Record<string, string>,
    [view.columns],
  );
  const columns = allColumns.filter((key) => !hidden[key]);

  // Filtering lives here rather than in the table, because the card's own row
  // count reports it: the artifact's header reads "6 of 10 rows" the moment the
  // filter box narrows the result.
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return rows;
    return rows.filter((row) =>
      columns.some((key) => display(row[key]).toLowerCase().includes(needle)),
    );
    // `columns` is derived from `hidden` and `rows` on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, hidden, query]);

  useEffect(() => {
    setQuery("");
    setHidden(defaultHidden(allColumns));
    setDatasetOpen(false);
    setChartKind(null);
    // `allColumns` is derived from the view's rows.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view]);

  // Close the columns menu on an outside click, or it stays open over whatever
  // the reader scrolls to next.
  useEffect(() => {
    if (!columnsOpen) return undefined;
    const onPointerDown = (event: MouseEvent) => {
      if (!columnsRef.current?.contains(event.target as Node)) {
        setColumnsOpen(false);
      }
    };
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, [columnsOpen]);

  const hasFullDataset =
    showResults && isSafeHttpUrl(view.resultS3Url) && !fullExportFailed;

  const exportCsv = async () => {
    if (!hasFullDataset) {
      downloadCsv(rows, "nl2sql-preview.csv");
      return;
    }
    setExporting(true);
    try {
      downloadCsv(await fetchDatasetRows(view.resultS3Url), "nl2sql-full.csv");
    } catch {
      // S3 unreachable (CORS/network): fall back to the preview rows and
      // relabel the button, so a partial export never passes for a full one.
      setFullExportFailed(true);
      if (rows.length) downloadCsv(rows, "nl2sql-preview.csv");
    } finally {
      setExporting(false);
    }
  };

  const copySql = async () => {
    if (!sql) return;
    const ok = await copyText(sql);
    setCopied(ok);
    setTimeout(() => setCopied(false), 1600);
  };

  const tabs: Array<{ key: TabKey; label: string; icon: IconName }> = [
    ...(resultChart
      ? [{ key: "chart" as const, label: "Chart", icon: "chart" as const }]
      : []),
    ...(rows.length
      ? [{ key: "data" as const, label: "Data", icon: "tbl" as const }]
      : []),
    ...(sql
      ? [{ key: "query" as const, label: "Query", icon: "code" as const }]
      : []),
    ...(rawEnabled
      ? [{ key: "raw" as const, label: "Raw", icon: "layers" as const }]
      : []),
  ];

  // The run produced nothing to look at, or an agent that shows none of it.
  if (!tabs.length) return null;

  const active =
    tab && tabs.some((entry) => entry.key === tab) ? tab : tabs[0].key;

  // Kinds this result can be drawn as, and the one on screen: the reader's
  // pick while it is still drawable, otherwise the service's suggestion.
  const kinds = chart ? availableKinds(chart.points) : [];
  const suggested = chart?.kind ?? "bar";
  const activeKind =
    chartKind && kinds.some((entry) => entry.key === chartKind)
      ? chartKind
      : kinds.some((entry) => entry.key === suggested)
        ? suggested
        : (kinds[0]?.key ?? suggested);

  const rowCountLabel =
    filtered.length !== rows.length
      ? `${filtered.length.toLocaleString()} of ${rows.length.toLocaleString()} rows`
      : view.rowCount === undefined
        ? `${rows.length.toLocaleString()} rows`
        : view.rowCountIsPreview
          ? `${view.rowCount.toLocaleString()} rows shown`
          : `${view.rowCount.toLocaleString()} rows`;

  return (
    <div
      className="overflow-hidden rounded-xl border border-n2s-line bg-n2s-card shadow-n2s-low"
      data-demo="result-card"
    >
      <div className="flex flex-wrap items-center gap-1.5 border-b border-n2s-line bg-n2s-card-2 px-2">
        <div role="tablist" aria-label="Result view" className="flex">
          {tabs.map((entry) => (
            <button
              key={entry.key}
              type="button"
              role="tab"
              data-demo={`tab-${entry.key}`}
              aria-selected={active === entry.key}
              onClick={() => setTab(entry.key)}
              className={`-mb-px inline-flex cursor-pointer items-center gap-1.5 border-0 border-b-2 bg-transparent px-2.5 py-2 text-[12px] font-semibold ${
                active === entry.key
                  ? "border-n2s-pri text-n2s-pri-ink"
                  : "border-transparent text-n2s-ink-3 hover:text-n2s-ink-2"
              }`}
            >
              <Icon name={entry.icon} className="size-3.5" strokeWidth={1.9} />
              {entry.label}
            </button>
          ))}
        </div>

        <div className="flex-1" />

        {active === "data" && (
          <div className="flex flex-wrap items-center gap-1.5 py-1">
            {view.tablesUsed[0] && (
              <span className="rounded-full bg-n2s-pri-wash px-2 py-0.5 font-mono text-[10.5px] font-bold text-n2s-pri-ink">
                {view.tablesUsed[0]}
              </span>
            )}
            <span className="text-[11px] text-n2s-ink-3">{rowCountLabel}</span>

            <div className="flex items-center gap-1.5 rounded-[7px] border border-n2s-line bg-n2s-card px-2 py-0.5">
              <Icon
                name="search"
                className="size-3 flex-none text-n2s-ink-3"
                strokeWidth={2}
              />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Filter rows"
                aria-label="Filter rows"
                className="w-24 border-0 bg-transparent text-[11.5px] text-n2s-ink outline-none placeholder:text-n2s-ink-3"
              />
            </div>

            <div className="relative" ref={columnsRef}>
              <button
                type="button"
                onClick={() => setColumnsOpen((open) => !open)}
                aria-expanded={columnsOpen}
                className="inline-flex cursor-pointer items-center gap-1.5 rounded-[7px] border border-n2s-line bg-n2s-card px-2 py-1 text-[11px] font-semibold text-n2s-ink-2 hover:bg-n2s-card-3"
              >
                <Icon name="tbl" className="size-3" strokeWidth={1.9} />
                Columns
                {allColumns.length > columns.length && (
                  <span
                    className="rounded-full bg-n2s-card-3 px-1.5 text-[10px] font-bold text-n2s-ink-3"
                    title={`${allColumns.length - columns.length} of ${allColumns.length} columns hidden`}
                  >
                    {allColumns.length - columns.length}
                  </span>
                )}
              </button>
              {columnsOpen && (
                <div className="absolute top-8 right-0 z-20 flex max-h-72 w-45 flex-col gap-px overflow-y-auto rounded-[10px] border border-n2s-line bg-n2s-card p-1.5 shadow-n2s-mid">
                  {allColumns.map((key) => {
                    const shown = !hidden[key];
                    // The last visible column cannot be hidden — a table with no
                    // columns reads as "no rows" rather than "nothing selected".
                    const locked = shown && columns.length === 1;
                    return (
                      <button
                        key={key}
                        type="button"
                        disabled={locked}
                        // Named for what the click does: the header button for
                        // the same column is called after the column itself.
                        aria-label={`${shown ? "Hide" : "Show"} ${key}`}
                        title={
                          locked
                            ? "At least one column stays visible"
                            : undefined
                        }
                        onClick={() =>
                          setHidden((current) => ({ ...current, [key]: shown }))
                        }
                        className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs text-n2s-ink-2 hover:bg-n2s-card-3 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        <span
                          className={`grid size-3.5 flex-none place-items-center rounded-sm text-white ${
                            shown
                              ? "bg-n2s-pri"
                              : "bg-transparent ring-1 ring-n2s-line ring-inset"
                          }`}
                        >
                          {shown && (
                            <Icon
                              name="chk"
                              className="size-2.5"
                              strokeWidth={3.6}
                            />
                          )}
                        </span>
                        <span className="truncate font-mono text-[11.5px]">
                          {key}
                        </span>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>

            <button
              type="button"
              onClick={exportCsv}
              disabled={exporting || (!hasFullDataset && !rows.length)}
              title={
                hasFullDataset
                  ? "Download every row of this result as CSV"
                  : "Only the preview rows are available for this result"
              }
              className="inline-flex cursor-pointer items-center gap-1.5 rounded-[7px] border border-n2s-line bg-n2s-card px-2 py-1 text-[11px] font-semibold text-n2s-ink-2 hover:bg-n2s-card-3 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Icon
                name={exporting ? "spinner" : "dn"}
                className={`size-3 ${exporting ? "animate-spin" : ""}`}
                strokeWidth={1.9}
              />
              {exporting
                ? "Downloading…"
                : hasFullDataset
                  ? "CSV"
                  : "CSV preview"}
            </button>

            {isSafeHttpUrl(view.resultS3Url) && (
              <button
                type="button"
                onClick={() => setDatasetOpen(true)}
                className="inline-flex cursor-pointer items-center gap-1.5 rounded-[7px] border border-n2s-line bg-n2s-card px-2 py-1 text-[11px] font-semibold text-n2s-ink-2 hover:bg-n2s-card-3"
              >
                <Icon name="expand" className="size-3" strokeWidth={1.9} />
                Full dataset
              </button>
            )}
          </div>
        )}

        {active === "chart" && chart && kinds.length > 1 && (
          <div
            role="group"
            aria-label="Chart type"
            className="flex items-center gap-0.5 rounded-[7px] border border-n2s-line bg-n2s-card p-0.5"
          >
            {kinds.map((option) => (
              <button
                key={option.key}
                type="button"
                onClick={() => setChartKind(option.key)}
                aria-pressed={activeKind === option.key}
                aria-label={`${option.label} chart`}
                title={
                  option.key === suggested
                    ? `${option.label} — suggested for this answer`
                    : option.label
                }
                className={`inline-grid size-6 cursor-pointer place-items-center rounded-[5px] border-0 ${
                  activeKind === option.key
                    ? "bg-n2s-pri-wash text-n2s-pri-ink"
                    : "bg-transparent text-n2s-ink-3 hover:bg-n2s-card-3 hover:text-n2s-ink-2"
                }`}
              >
                <Icon
                  name={option.icon}
                  className="size-3.5"
                  strokeWidth={1.9}
                />
              </button>
            ))}
          </div>
        )}

        {active === "query" && (
          <div className="flex items-center gap-1.5 py-1">
            {view.executionTimeMs !== undefined && (
              <span className="font-mono text-[11px] text-n2s-ink-3">
                {(view.executionTimeMs / 1000).toFixed(2)}s
              </span>
            )}
            <button
              type="button"
              onClick={copySql}
              className="inline-flex cursor-pointer items-center gap-1.5 rounded-[7px] border border-n2s-line bg-n2s-card px-2 py-1 text-[11px] font-semibold text-n2s-ink-2 hover:bg-n2s-card-3"
            >
              <Icon name="copy" className="size-3" strokeWidth={1.9} />
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
        )}
      </div>

      {active === "data" && (
        <ResultTable
          rows={filtered}
          columns={columns}
          types={columnTypes}
          totalRows={rows.length}
          query={query}
        />
      )}

      {active === "chart" && resultChart && (
        <div className="flex flex-col gap-3 px-4 pt-3 pb-4">
          {/* The run's own title for the result, when it sent one — the type of
              chart is the chip below, not the heading. */}
          {(view.chart?.metadata as { title?: string } | undefined)?.title && (
            <h4 className="m-0 text-[13px] font-bold text-n2s-ink">
              {chartTitle}
            </h4>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-1.5 text-[11.5px] text-n2s-ink-2">
              <span className="font-semibold">Suggested chart:</span>
              {view.chart?.suggestion ?? "chart"}
            </span>
            {/* The suggestion stays on screen when the reader draws the result
                another way, so the card never claims the service asked for the
                view they picked. */}
            {chart && activeKind !== suggested && (
              <span className="inline-flex items-baseline gap-1.5 rounded-full bg-n2s-card-3 px-2 py-0.5 text-[10.5px] text-n2s-ink-2">
                <span className="font-bold">Shown as</span>
                {KIND_LABEL[activeKind]}
              </span>
            )}
            {[
              chartAxes?.xLabel && { label: "X", value: chartAxes.xLabel },
              chartAxes?.yLabel && { label: "Y", value: chartAxes.yLabel },
            ]
              .filter((meta): meta is { label: string; value: string } =>
                Boolean(meta),
              )
              .map((meta) => (
                <span
                  key={meta.label}
                  className="inline-flex items-baseline gap-1.5 rounded-full bg-n2s-card-3 px-2 py-0.5 text-[10.5px] text-n2s-ink-2"
                >
                  <span className="font-bold">{meta.label}</span>
                  <span className="font-mono">{meta.value}</span>
                </span>
              ))}
          </div>
          {resultChart.shape === "flat" && (
            <ResultChart
              chart={resultChart.chart}
              kind={activeKind}
              title={chartTitle}
            />
          )}
          {resultChart.shape === "stacked" && (
            <StackedResultChart chart={resultChart.chart} title={chartTitle} />
          )}
          {resultChart.shape === "invalid" && (
            <p
              role="status"
              className="m-0 rounded-lg border border-n2s-line bg-n2s-card-2 p-3 text-sm text-n2s-ink-2"
            >
              This chart cannot be drawn: {resultChart.reason}
              {rows.length > 0 && " The returned data remains available."}
              {sql && " The query remains available."}
            </p>
          )}
        </div>
      )}

      {active === "query" && sql && (
        <pre className="m-0 max-h-[280px] overflow-auto bg-n2s-card-2 p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap text-n2s-ink-2">
          {highlightSql(sql)}
        </pre>
      )}

      {active === "raw" && (
        <pre className="m-0 max-h-[280px] overflow-auto bg-n2s-card-2 p-3 font-mono text-[11px] leading-relaxed whitespace-pre text-n2s-ink-2">
          {JSON.stringify(raw, null, 2)}
        </pre>
      )}

      <FullDatasetModal
        open={datasetOpen}
        resultS3Url={view.resultS3Url}
        fallbackRows={view.previewRows}
        onClose={() => setDatasetOpen(false)}
      />
    </div>
  );
}
