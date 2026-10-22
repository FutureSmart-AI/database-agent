"use client";

import { useEffect, useState } from "react";
import dynamic from "next/dynamic";

import type { UseQueryResult } from "@tanstack/react-query";
import dayjs from "dayjs";

import Icon from "@/components/Icon";
import {
  FAILURE_CATEGORIES,
  useFailures,
  type FailureOwner,
} from "@/data/analyticsFailures";
import { NL2SQL_FAILURE_OPTIONS } from "@/lib/analyticsContractOptions";
import ChartCard from "@/platform/analytics/components/ChartCard";
import DataState from "@/platform/analytics/components/DataState";
import KpiCard from "@/platform/analytics/components/KpiCard";
import KpiGrid from "@/platform/analytics/components/KpiGrid";
import type { AnalyticsWindow, Scorecard } from "@/platform/analytics/types";
import { TablePagination } from "@/platform/components/ui";
import { cn } from "@/platform/utils";

const FailureBreakdownChart = dynamic(
  () => import("../charts/FailureBreakdownChart"),
  { ssr: false },
);

/**
 * Failures — the one tab with no agent-dashboard counterpart.
 *
 * `GET …/analytics/failures` is NL2SQL-only: the dashboard's analytics has no
 * equivalent route, because "the database rejected the generated SQL" is not a
 * failure mode a RAG agent has. It answers the question the Quality tab raises
 * and cannot settle — *why* the unanswered ones failed — so it sits directly
 * after it.
 *
 * `top_failed_queries` is grouped by normalised question, one row per distinct
 * question with an `occurrences` count. That grouping is the point: six
 * failures of one misspelled table name is one thing to fix, not six.
 */

const OWNER_STYLE: Record<FailureOwner, { label: string; className: string }> =
  {
    model: { label: "Model", className: "bg-violet-50 text-violet-700" },
    operator: { label: "Operator", className: "bg-amber-50 text-amber-700" },
    schema: { label: "Schema", className: "bg-sky-50 text-sky-700" },
    infrastructure: {
      label: "Infrastructure",
      className: "bg-orange-50 text-orange-700",
    },
    question: { label: "Question", className: "bg-slate-100 text-slate-600" },
    us: { label: "Us", className: "bg-red-50 text-red-700" },
    unknown: {
      label: "Unclassified",
      className: "bg-slate-100 text-slate-500",
    },
  };

const categoryMeta = (key: string | null) =>
  (key && FAILURE_CATEGORIES[key]) || {
    label: key ?? "—",
    means: "Not one of the documented categories.",
    owner: "unknown" as FailureOwner,
  };

function OwnerBadge({ owner }: { owner: FailureOwner }) {
  const style = OWNER_STYLE[owner];
  return (
    <span
      className={cn(
        "inline-flex rounded px-1.5 py-0.5 text-[10px] font-medium",
        style.className,
      )}
    >
      {style.label}
    </span>
  );
}

export default function FailuresTab({
  scorecard,
  window,
  agentId,
}: {
  scorecard: UseQueryResult<Scorecard>;
  window: AnalyticsWindow;
  agentId?: string | null;
  onTabChange?: (tab: string) => void;
}) {
  const [category, setCategory] = useState<string | null>(null);
  const [stage, setStage] = useState<string | null>(null);
  // Page size and its choices come from the service's own spec, not from a
  // number picked here: `/failures` defaults to 50 rows and caps at 200, and
  // asking for more than the cap is a 422.
  const [pageSize, setPageSize] = useState(NL2SQL_FAILURE_OPTIONS.pageSizes[0]);
  const [pageIndex, setPageIndex] = useState(0);

  // A narrower filter or a different window means a different result set, and
  // page 4 of it almost certainly does not exist.
  useEffect(() => {
    setPageIndex(0);
  }, [category, stage, window]);

  const failures = useFailures(agentId, window, {
    category: category ?? undefined,
    failed_stage: stage ?? undefined,
    limit: pageSize,
    offset: pageIndex * pageSize,
  });

  const data = failures.data;
  const rows = data?.top_failed_queries ?? [];
  // `/failures` reports no total for this list — only `total_failures`, which
  // counts failures rather than the distinct questions they group into. A full
  // page is the only evidence there may be another.
  const hasMore = rows.length === pageSize;
  const totalQueries = scorecard.data?.usage?.total_queries ?? 0;
  const totalFailures = data?.total_failures ?? 0;
  // Rate against the window's whole query count, not against failures — the
  // question the card answers is "how much of the traffic broke".
  const failureRate =
    totalQueries > 0 ? (totalFailures / totalQueries) * 100 : null;

  const byCategory = data?.by_category ?? [];
  const byStage = data?.by_stage ?? [];
  const topCategory = byCategory[0];
  const topStage = byStage[0];

  const categoryData = byCategory.map((row) => ({
    label: categoryMeta(row.failure_category).label,
    count: row.count,
    key: row.failure_category,
  }));
  const stageData = byStage.map((row) => ({
    label: row.failed_stage,
    count: row.count,
  }));

  const clearFilters = () => {
    setCategory(null);
    setStage(null);
  };
  const filtered = category || stage;

  return (
    <div className="space-y-4">
      <KpiGrid>
        <KpiCard
          label="Total Failures"
          value={failures.isLoading ? "…" : totalFailures.toLocaleString()}
          valueSize="lg"
          icon={<Icon name="xCircle" className="size-4 text-red-500" />}
          iconBg="bg-red-50"
          hint="Queries that did not produce a usable answer in this window"
          isLoading={failures.isLoading}
        />
        <KpiCard
          label="Failure Rate"
          value={failureRate == null ? "—" : `${failureRate.toFixed(1)}%`}
          valueSize="lg"
          icon={<Icon name="percent" className="size-4 text-amber-500" />}
          iconBg="bg-amber-50"
          hint={
            totalQueries > 0
              ? "Failures ÷ every query asked in this window"
              : "No queries in this window to rate against"
          }
          isLoading={failures.isLoading || scorecard.isLoading}
        />
        <KpiCard
          label="Top Category"
          value={
            topCategory ? categoryMeta(topCategory.failure_category).label : "—"
          }
          valueSize="lg"
          icon={<Icon name="warn" className="size-4 text-violet-500" />}
          iconBg="bg-violet-50"
          hint={
            topCategory
              ? `${topCategory.count} of ${totalFailures} — ${categoryMeta(topCategory.failure_category).means.toLowerCase()}`
              : "Nothing failed in this window"
          }
          isLoading={failures.isLoading}
        />
        <KpiCard
          label="Top Failing Stage"
          value={topStage?.failed_stage ?? "—"}
          valueSize="lg"
          icon={<Icon name="layers" className="size-4 text-sky-500" />}
          iconBg="bg-sky-50"
          hint={
            topStage
              ? `The graph node ${topStage.count} failures stopped at`
              : "No stage recorded a failure"
          }
          isLoading={failures.isLoading}
        />
        <KpiCard
          label="Distinct Questions"
          value={
            failures.isLoading
              ? "…"
              : `${hasMore ? "≥" : ""}${(pageIndex * pageSize + rows.length).toLocaleString()}`
          }
          valueSize="lg"
          icon={<Icon name="warn" className="size-4 text-slate-400" />}
          iconBg="bg-slate-100"
          // The endpoint pages this list and publishes no total for it, so a
          // full page means "at least this many" — printing the page's length
          // as the count would understate it by however many pages follow.
          hint={
            hasMore
              ? "At least this many — page through the table to see the rest"
              : "Failures grouped by normalised question — what there is to fix"
          }
          isLoading={failures.isLoading}
        />
      </KpiGrid>

      <div className="flex gap-4 max-md:flex-col">
        <ChartCard
          title="Failures by Category"
          subtitle="Click a bar to filter the table below"
          className="h-[280px]"
        >
          <DataState
            isLoading={failures.isLoading}
            isError={failures.isError}
            isEmpty={!categoryData.length}
            emptyText="Nothing failed in this period."
          >
            <div className="h-[200px]">
              <FailureBreakdownChart
                data={categoryData}
                selected={category ? categoryMeta(category).label : null}
                onSelect={(label) => {
                  const hit = categoryData.find((r) => r.label === label);
                  setCategory((cur) =>
                    hit && cur === hit.key ? null : (hit?.key ?? null),
                  );
                }}
              />
            </div>
          </DataState>
        </ChartCard>

        <ChartCard
          title="Failures by Stage"
          subtitle="The graph node the query stopped at"
          className="h-[280px]"
        >
          <DataState
            isLoading={failures.isLoading}
            isError={failures.isError}
            isEmpty={!stageData.length}
            emptyText="Nothing failed in this period."
          >
            <div className="h-[200px]">
              <FailureBreakdownChart
                data={stageData}
                selected={stage}
                onSelect={(label) =>
                  setStage((cur) => (cur === label ? null : label))
                }
              />
            </div>
          </DataState>
        </ChartCard>
      </div>

      <ChartCard
        title="Top Failing Questions"
        subtitle="Grouped by normalised question — one row per distinct question, not per failure"
        action={
          filtered ? (
            <button
              type="button"
              onClick={clearFilters}
              className="cursor-pointer rounded border border-slate-200 px-2 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50"
            >
              Clear filter
            </button>
          ) : undefined
        }
      >
        <DataState
          isLoading={failures.isLoading}
          isError={failures.isError}
          isEmpty={!rows.length}
          emptyText={
            filtered
              ? "No failing questions match this filter."
              : "No failing questions in this period."
          }
        >
          <div className="overflow-x-auto">
            <table className="w-full min-w-[820px] text-left text-sm">
              <thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-2 py-2.5">Question</th>
                  <th className="px-2 py-2.5">Category</th>
                  <th className="px-2 py-2.5">Stage</th>
                  <th className="px-2 py-2.5 text-right">Occurrences</th>
                  <th className="px-2 py-2.5">Last seen</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row, i) => {
                  const meta = categoryMeta(row.failure_category);
                  return (
                    <tr
                      key={`${row.query_norm}-${i}`}
                      className="border-b border-slate-100 last:border-0 align-top"
                    >
                      <td className="max-w-[380px] px-2 py-2.5">
                        <div className="truncate font-medium text-slate-700">
                          {row.query_norm}
                        </div>
                        {row.sample_failure_detail && (
                          <div className="mt-0.5 truncate font-mono text-xs text-red-500">
                            {row.sample_failure_detail}
                          </div>
                        )}
                      </td>
                      <td className="px-2 py-2.5">
                        <div className="flex flex-col items-start gap-1">
                          <span className="text-slate-700">{meta.label}</span>
                          <OwnerBadge owner={meta.owner} />
                        </div>
                      </td>
                      <td className="px-2 py-2.5 font-mono text-xs text-slate-500">
                        {row.failed_stage ?? "—"}
                      </td>
                      <td className="px-2 py-2.5 text-right font-semibold text-slate-700">
                        {row.occurrences}
                      </td>
                      <td className="px-2 py-2.5 text-xs text-slate-500">
                        {row.last_seen
                          ? dayjs(row.last_seen).format("MMM D, HH:mm")
                          : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </DataState>

        {/*
          Outside `DataState`, deliberately: paging past the last page lands on
          an empty result, and a footer that disappears with the rows would
          strand the reader there with no way back.
        */}
        {(hasMore || pageIndex > 0) && (
          <TablePagination
            pageIndex={pageIndex}
            pageSize={pageSize}
            // No `totalItems`: the endpoint publishes none for this list, and
            // inventing one from `total_failures` would number pages that do
            // not exist — these rows are questions, those are failures.
            hasMore={hasMore}
            pageSizeOptions={NL2SQL_FAILURE_OPTIONS.pageSizes}
            disabled={failures.isFetching}
            onPageChange={(p) => {
              setPageIndex(p.pageSize === pageSize ? p.pageIndex : 0);
              setPageSize(p.pageSize);
            }}
            className="border-t border-slate-100"
          />
        )}
      </ChartCard>
    </div>
  );
}
