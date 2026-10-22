"use client";

import { useEffect } from "react";

import Icon from "@/components/Icon";
import { RowsSkeleton } from "@/components/ui/Skeletons";
import {
  metricTotal,
  tokenCost,
  useUsageAggregate,
  type AggregateGroup,
  type UsageFilters,
  type UsagePeriod,
  type UsageSource,
} from "@/data/usage";
import { apiMessage } from "@/lib/apiError";
import { nfmt } from "@/lib/format";
import { cn } from "@/platform/utils";

import type { AccountMetricKey } from "./constants";

/**
 * The model-and-provider breakdown behind any figure on this screen.
 *
 * Opened by a metric card, a service card or an agent row. Every one of them
 * asks the same question — `group_by=model&group_by=provider`, plus whatever
 * filter the card already carried — so this is one component with a different
 * filter, not a drawer per surface.
 *
 * `model: null` and `provider: null` are real data, not an error: `db_query`
 * and `code_execution` events have no model. Those groups are kept and counted,
 * and the drawer says there is no model-level detail rather than dropping the
 * rows and reporting a smaller total than the card the reader clicked.
 */

export interface DrawerSpec {
  title: string;
  /** Which figure the bars measure. */
  metric: AccountMetricKey;
  /** The filter the opening surface already had. */
  filters: UsageFilters;
  /** Extra line under the title, naming the scope. */
  scope: string;
}

function groupValue(group: AggregateGroup, metric: AccountMetricKey): number {
  if (metric === "requests") return group.event_count ?? 0;
  return metricTotal(group, metric);
}

export default function BreakdownDrawer({
  spec,
  period,
  source,
  periodLabel,
  sourceLabel,
  tokenRate,
  onClose,
}: {
  spec: DrawerSpec;
  period: UsagePeriod;
  source: UsageSource;
  periodLabel: string;
  sourceLabel: string;
  tokenRate: number | undefined;
  onClose: () => void;
}) {
  const breakdown = useUsageAggregate(
    ["model", "provider"],
    period,
    source,
    spec.filters,
  );

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const groups = breakdown.data?.groups ?? [];
  const withModel = groups.filter((group) => group.model);
  const withoutModel = groups.filter((group) => !group.model);

  const rows = withModel
    .map((group) => ({
      model: group.model as string,
      provider: group.provider ?? "—",
      value: groupValue(group, spec.metric),
      requests: group.event_count ?? 0,
      tokens: metricTotal(group, "total_tokens"),
    }))
    .filter((row) => row.value > 0)
    .sort((a, b) => b.value - a.value);

  const top = rows.length ? rows[0].value : 1;
  const total = groups.reduce(
    (sum, group) => sum + groupValue(group, spec.metric),
    0,
  );
  const totalTokens = groups.reduce(
    (sum, group) => sum + metricTotal(group, "total_tokens"),
    0,
  );
  const totalRequests = groups.reduce(
    (sum, group) => sum + (group.event_count ?? 0),
    0,
  );
  const unattributed = withoutModel.reduce(
    (sum, group) => sum + (group.event_count ?? 0),
    0,
  );

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <button
        type="button"
        aria-label="Close breakdown"
        className="absolute inset-0 cursor-default bg-slate-900/25"
        onClick={onClose}
      />
      <aside
        role="dialog"
        aria-modal="true"
        aria-label={`${spec.title} breakdown`}
        className="relative flex h-full w-full max-w-md flex-col overflow-hidden border-l border-slate-200 bg-white shadow-2xl"
      >
        <header className="flex items-start gap-3 border-b border-slate-100 px-5 py-4">
          <div className="min-w-0 flex-1">
            <h2 className="text-base font-bold text-slate-900">{spec.title}</h2>
            <p className="mt-0.5 text-xs text-slate-400">
              Breakdown by model and provider · {spec.scope}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-50 hover:text-slate-700"
          >
            <Icon name="x" className="size-4" />
          </button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          <div className="mb-4 grid grid-cols-3 gap-2">
            <Tile
              label="Total"
              value={
                spec.metric === "requests"
                  ? nfmt(total)
                  : nfmt(Math.round(total))
              }
              foot={spec.metric === "requests" ? "requests" : "tokens"}
            />
            <Tile
              label="Cost"
              value={`$${tokenCost(totalTokens, tokenRate).toFixed(4)}`}
              foot={tokenRate ? `at $${tokenRate} / token` : "rate unavailable"}
            />
            <Tile
              label="Requests"
              value={nfmt(totalRequests)}
              foot="billed operations"
            />
          </div>

          {breakdown.isLoading ? (
            <RowsSkeleton rows={4} />
          ) : breakdown.error ? (
            <p className="text-sm text-rose-600">
              {apiMessage(breakdown.error)}
            </p>
          ) : rows.length ? (
            <div className="space-y-3.5">
              {rows.map((row) => (
                <div key={`${row.provider}/${row.model}`}>
                  <div className="flex items-start gap-2">
                    <span className="min-w-0 flex-1">
                      <b className="block truncate font-mono text-xs text-slate-800">
                        {row.model}
                      </b>
                      <span className="text-[11px] text-slate-400">
                        {row.provider}
                      </span>
                    </span>
                    <span className="text-sm font-extrabold tabular-nums text-slate-900">
                      {nfmt(Math.round(row.value))}
                    </span>
                  </div>
                  <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-slate-100">
                    <div
                      className="h-full rounded-full bg-blue-600"
                      style={{
                        width: `${((row.value / top) * 100).toFixed(1)}%`,
                      }}
                    />
                  </div>
                  <p className="mt-1 text-[11px] text-slate-400">
                    {nfmt(row.requests)} requests ·{" "}
                    {`$${tokenCost(row.tokens, tokenRate).toFixed(4)}`}
                  </p>
                </div>
              ))}
            </div>
          ) : (
            <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-8 text-center">
              <p className="text-sm font-bold text-slate-700">
                No model-level detail
              </p>
              <p className="mx-auto mt-1.5 max-w-[42ch] text-xs leading-relaxed text-slate-500">
                {unattributed
                  ? `${nfmt(unattributed)} operations here ran without a model — database queries and code executions are recorded with no model or provider, so there is nothing to split by.`
                  : "Nothing was served by a model under this filter."}
              </p>
            </div>
          )}

          {rows.length > 0 && unattributed > 0 && (
            <p className="mt-4 text-[11px] leading-relaxed text-slate-400">
              A further {nfmt(unattributed)} operations ran without a model —
              database queries and code executions carry no model or provider,
              and are counted in the totals above but cannot be split by model.
            </p>
          )}
        </div>

        <footer className="border-t border-slate-100 px-5 py-3 text-[11px] text-slate-400">
          {periodLabel} · {sourceLabel}
        </footer>
      </aside>
    </div>
  );
}

function Tile({
  label,
  value,
  foot,
}: {
  label: string;
  value: string;
  foot: string;
}) {
  return (
    <div
      className={cn("rounded-lg border border-slate-200 bg-slate-50 px-3 py-2")}
    >
      <p className="text-[10px] font-bold tracking-wide text-slate-400 uppercase">
        {label}
      </p>
      <p className="mt-0.5 text-sm font-extrabold tabular-nums text-slate-900">
        {value}
      </p>
      <p className="mt-0.5 text-[10px] text-slate-400">{foot}</p>
    </div>
  );
}
