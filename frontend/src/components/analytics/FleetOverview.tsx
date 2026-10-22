"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import Icon from "@/components/Icon";
import {
  useAnalyticsOverview,
  type OverviewAgentRow,
  type OverviewSort,
} from "@/data/analyticsOverview";
import { useAgents, useSharedAgents } from "@/data/useAgents";
import { NL2SQL_OVERVIEW_OPTIONS } from "@/lib/analyticsContractOptions";
import { apiMessage } from "@/lib/apiError";
import { ms, nfmt, pct } from "@/lib/format";
import { agentRoute, ROUTES } from "@/lib/routes";
import { TABLE } from "@/lib/tableStyles";
import AnalyticsToolbar from "@/platform/analytics/components/AnalyticsToolbar";
import { useAnalyticsWindow } from "@/platform/analytics/hooks/useAnalyticsWindow";
import { TablePagination } from "@/platform/components/ui";
import { cn } from "@/platform/utils";

import { Card, CardBody, CardHeader } from "../ui/Card";
import EmptyState from "../ui/EmptyState";
import { TableSkeleton } from "../ui/Skeletons";

/**
 * Every agent's analytics in one grid — `GET /v1/agents/analytics/overview`.
 *
 * The route existed and nothing called it. Analytics opened on an agent
 * picker, so "which agent is failing, which is expensive" could only be
 * answered one agent at a time, and the picker's cards said nothing about
 * either. This replaces that picker with the same list of agents carrying the
 * numbers, and each row is still the way in to one agent's screen.
 *
 * `summary` describes the whole window *before* search and paging, so it is
 * labelled as the window's total and never as the sum of the rows on screen —
 * they genuinely differ, by design, and a total that shrank as you paged would
 * be useless.
 */

const HEADINGS: {
  key: OverviewSort | null;
  label: string;
  numeric: boolean;
}[] = [
  { key: null, label: "Agent", numeric: false },
  { key: "total_queries", label: "Queries", numeric: true },
  { key: null, label: "Users", numeric: true },
  { key: "success_rate", label: "Success", numeric: true },
  { key: "avg_ms", label: "Avg", numeric: true },
  { key: null, label: "P95", numeric: true },
  { key: "total_cost", label: "Cost", numeric: true },
  { key: null, label: "Top failure", numeric: false },
];

function SortIcon({
  active,
  order,
}: {
  active: boolean;
  order: "asc" | "desc";
}) {
  if (!active)
    return <Icon name="caretUpDown" className="size-3 text-slate-300" />;
  return order === "asc" ? (
    <Icon name="up" className="size-3 text-indigo-500" />
  ) : (
    <Icon name="down" className="size-3 text-indigo-500" />
  );
}

const usd = (n: number | null | undefined) =>
  n == null ? "—" : `$${n.toFixed(n < 1 ? 4 : 2)}`;

export default function FleetOverview({
  /** Rendered instead of the grid when no agent has recorded anything yet. */
  fallback,
}: {
  fallback?: React.ReactNode;
}) {
  const { window, setWindow } = useAnalyticsWindow();
  const [sort, setSort] = useState<OverviewSort | undefined>();
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  const [search, setSearch] = useState("");
  const [pageSize, setPageSize] = useState(
    NL2SQL_OVERVIEW_OPTIONS.pageSizes[0],
  );
  const [pageIndex, setPageIndex] = useState(0);

  // A new window, a new search or a new sort is a different result set; page 3
  // of the previous one is not a page of this one.
  useEffect(() => {
    setPageIndex(0);
  }, [window, search, sort, order, pageSize]);

  const overview = useAnalyticsOverview(window, {
    sort,
    order,
    q: search.trim() || undefined,
    limit: pageSize,
    offset: pageIndex * pageSize,
  });

  /**
   * Rows are keyed by the NL2SQL `agent_id`; this product's URLs are keyed by
   * the agent record whose `service_ref` is that id. Today the two coincide —
   * `toAgent` sets `service_ref` from the row's own id — but the analytics
   * service is free to key on something else, and a row that links to an agent
   * page which cannot resolve it is worse than one that does not link. So the
   * link exists only where a record claims the id, and every other row renders
   * as plain text.
   */
  const { agents } = useAgents();
  const shared = useSharedAgents();
  const byServiceRef = new Map(
    [...agents, ...shared.agents]
      .filter((a) => a.service_ref)
      .map((a) => [a.service_ref as string, a.agent_id]),
  );

  const data = overview.data;
  const rows = data?.agents ?? [];
  const total = data?.total_agents ?? 0;

  const toggleSort = (key: OverviewSort) => {
    if (key === sort) setOrder((o) => (o === "desc" ? "asc" : "desc"));
    else {
      setSort(key);
      setOrder("desc");
    }
  };

  // Nothing recorded anywhere, and nothing being searched for: the workspace
  // is new rather than empty-for-this-filter, so offer the picker instead of a
  // grid with no rows.
  if (
    fallback &&
    !overview.isLoading &&
    !overview.isError &&
    total === 0 &&
    !search
  ) {
    return <>{fallback}</>;
  }

  return (
    <div className="space-y-4">
      <AnalyticsToolbar window={window} onWindowChange={setWindow} />

      <Card className="overflow-hidden">
        <CardHeader
          title="All agents"
          note={
            data
              ? `${nfmt(data.summary.total_queries)} queries · ${usd(data.summary.total_cost)} across this window`
              : "Usage, quality and cost per agent"
          }
          action={
            <div className="relative">
              <Icon
                name="search"
                className="pointer-events-none absolute left-2.5 top-1/2 size-3 -translate-y-1/2 text-slate-400"
              />
              <input
                aria-label="Search agents"
                placeholder="Search agent id…"
                className="w-56 rounded-md border border-slate-200 bg-white py-1.5 pl-7 pr-2.5 text-xs text-slate-700 focus:border-indigo-500 focus:outline-none"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
          }
        />

        {data && !data.summary.cost_complete && (
          <div className="border-b border-amber-200 bg-amber-50 px-4 py-2 text-xs text-amber-700">
            Some queries in this window are still unpriced — cost figures are a
            lower bound. Open an agent and refresh its costs to reconcile.
          </div>
        )}

        {overview.isLoading ? (
          <TableSkeleton cols={HEADINGS.length} />
        ) : overview.isError ? (
          <CardBody className="text-sm text-rose-600">
            {apiMessage(overview.error)}
          </CardBody>
        ) : !rows.length ? (
          <EmptyState
            icon="chart"
            title="No agents match"
            note={
              search
                ? "No agent id contains that text in this window."
                : "No agent recorded a query in this window."
            }
          />
        ) : (
          <>
            <div className={TABLE.wrap}>
              <table className={TABLE.table}>
                <thead>
                  <tr className={TABLE.headRow}>
                    {HEADINGS.map((head) => (
                      <th
                        key={head.label}
                        className={head.numeric ? TABLE.thNumeric : TABLE.th}
                      >
                        {head.key ? (
                          <button
                            type="button"
                            onClick={() => toggleSort(head.key as OverviewSort)}
                            className={cn(
                              "inline-flex cursor-pointer items-center gap-1",
                              head.numeric && "flex-row-reverse",
                            )}
                          >
                            {head.label}
                            <SortIcon
                              active={sort === head.key}
                              order={order}
                            />
                          </button>
                        ) : (
                          head.label
                        )}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <FleetRow
                      key={row.agent_id}
                      row={row}
                      href={
                        byServiceRef.has(row.agent_id)
                          ? agentRoute(
                              ROUTES.analytics,
                              byServiceRef.get(row.agent_id) as string,
                            )
                          : null
                      }
                    />
                  ))}
                </tbody>
              </table>
            </div>

            <TablePagination
              pageIndex={pageIndex}
              pageSize={pageSize}
              totalItems={total}
              pageSizeOptions={NL2SQL_OVERVIEW_OPTIONS.pageSizes}
              disabled={overview.isFetching}
              onPageChange={(p) => {
                setPageIndex(p.pageSize === pageSize ? p.pageIndex : 0);
                setPageSize(p.pageSize);
              }}
            />
          </>
        )}
      </Card>
    </div>
  );
}

function FleetRow({
  row,
  href,
}: {
  row: OverviewAgentRow;
  href: string | null;
}) {
  return (
    <tr className={TABLE.row}>
      <td className={TABLE.td}>
        {href ? (
          <Link
            href={href}
            className="font-medium text-indigo-600 hover:underline"
          >
            {row.name ?? row.agent_id}
          </Link>
        ) : (
          <span className="font-medium text-slate-700">
            {row.name ?? row.agent_id}
          </span>
        )}
        {row.name && (
          <div className="font-mono text-[11px] text-slate-400">
            {row.agent_id}
          </div>
        )}
      </td>
      <td className={TABLE.tdNumeric}>{nfmt(row.total_queries)}</td>
      <td className={TABLE.tdNumeric}>
        {row.unique_users == null ? "—" : nfmt(row.unique_users)}
      </td>
      <td className={TABLE.tdNumeric}>
        {row.success_rate == null ? "—" : pct(row.success_rate)}
      </td>
      <td className={TABLE.tdNumeric}>
        {row.avg_ms == null ? "—" : ms(row.avg_ms)}
      </td>
      <td className={TABLE.tdNumeric}>
        {row.p95_ms == null ? "—" : ms(row.p95_ms)}
      </td>
      <td className={TABLE.tdNumeric}>
        {usd(row.total_cost)}
        {/* Never render an unpriced total as a settled one. */}
        {!row.cost_complete && (
          <span className="ml-1 text-amber-500" title="Some queries unpriced">
            +
          </span>
        )}
      </td>
      <td className={TABLE.td}>
        {row.top_failure_category ? (
          <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-600">
            {row.top_failure_category}
          </span>
        ) : (
          <span className="text-slate-400">—</span>
        )}
      </td>
    </tr>
  );
}
