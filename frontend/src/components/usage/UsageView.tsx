"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";

import Donut from "@/components/charts/Donut";
import Icon from "@/components/Icon";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import Field from "@/components/ui/Field";
import {
  metricAvg,
  metricTotal,
  periodLabel as periodLabelFor,
  tokenCost,
  useOwnerLimits,
  useUsageAggregate,
  useUsageTotals,
  useUsageTrend,
  type AggregateGroup,
  type UsageBucket,
  type UsageFilters,
  type UsagePeriod,
  type UsageSource,
} from "@/data/usage";
import { useAgents } from "@/data/useAgents";
import { SERIES } from "@/lib/colors";
import { ms, nfmt } from "@/lib/format";
import { ROUTES } from "@/lib/routes";
import { TABLE } from "@/lib/tableStyles";
import { Select } from "@/platform/components/ui";
import { cn } from "@/platform/utils";

import BreakdownDrawer, { type DrawerSpec } from "./BreakdownDrawer";
import {
  ACCOUNT_METRICS,
  SERVICE_OPERATIONS,
  TABS,
  USAGE_NAV_ICONS,
  USAGE_PERIOD_OPTIONS,
  USAGE_SOURCE_OPTIONS,
  type AccountMetricKey,
} from "./constants";
import PlanLimits from "./PlanLimits";
import UsageTrendChart, { type TrendMetric } from "./UsageTrendChart";

/**
 * Account-wide usage, across every database agent in the workspace.
 *
 * Four reads back the whole screen — `/v1/aggregate`, `/v1/trend`,
 * `/v1/owners/me/limits` and (behind the drawer) `/v1/aggregate` again. Three
 * contract rules are load-bearing here and are not re-derived:
 *
 * · **There is no ungrouped total.** The account figures come from one
 *   `group_by=key_type` call, and Total is the sum of its platform and own-key
 *   groups. A separately-fetched total would be a third number that can
 *   disagree with its own parts.
 * · **No endpoint returns cost.** Cost is `total_tokens × token_rate_usd`, with
 *   the rate from `/limits` — which is why the Overview reads the limits call
 *   too. It is rounded for display only.
 * · **`service_type` is not a grouping.** Every row here is `nl2sql`, so the
 *   service 422s rather than returning one group; the Custom Filters tab used
 *   to offer it as a breakdown and got a 422 for it.
 *
 * On the Limits tab both the consumption source and the period are disabled: a
 * limit counts every request whichever key paid for it, and its window is fixed
 * in `billing_window`.
 */

type UsageTab = (typeof TABS)[number]["key"];

function asUsageTab(value: string): UsageTab | null {
  return TABS.some((tab) => tab.key === value) ? (value as UsageTab) : null;
}

function money(value: number): string {
  if (value > 0 && value < 0.01) return `$${value.toFixed(4)}`;
  return `$${value.toFixed(2)}`;
}

/* ── the pieces ─────────────────────────────────────────────────────────── */

/**
 * The cost of the selected period, with the arithmetic shown.
 *
 * Under Total the platform and own-key sides are added in front of the reader,
 * because that sum IS the total — there is no separate total to fetch. Under
 * Platform or Owner only that side is shown, and the note says so rather than
 * letting one side look like the whole bill.
 */
function CostStrip({
  platformTokens,
  ownerTokens,
  tokenRate,
  source,
  sourceLabel,
  periodLabel,
}: {
  platformTokens: number;
  ownerTokens: number;
  tokenRate: number | undefined;
  source: UsageSource;
  sourceLabel: string;
  periodLabel: string;
}) {
  const platform = tokenCost(platformTokens, tokenRate);
  const owner = tokenCost(ownerTokens, tokenRate);

  const note =
    source === "platform"
      ? "Platform consumption only — spend billed to your own provider keys is not included in this figure."
      : source === "owner"
        ? "Owner consumption only — spend billed to FutureSmart platform keys is not included in this figure."
        : "Platform spend plus spend billed to your own provider keys.";

  return (
    <section className="mb-4 rounded-xl border border-black/5 bg-white px-4 py-3.5 shadow-sm sm:px-5">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-bold text-slate-900">
          Total estimated cost
        </h2>
        <span className="rounded-full bg-slate-50 px-2 py-0.5 text-[11px] font-semibold text-slate-600 ring-1 ring-slate-200 ring-inset">
          {sourceLabel}
        </span>
        <span className="text-xs text-slate-400">{periodLabel}</span>
      </div>
      <div className="mt-1.5 flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
        {source === "total" ? (
          <>
            <CostPart label="Platform" value={platform} />
            <span
              aria-hidden="true"
              className="self-center px-0.5 text-[17px] font-bold text-slate-400"
            >
              +
            </span>
            <CostPart label="Your own keys" value={owner} />
            <span
              aria-hidden="true"
              className="self-center px-0.5 text-[17px] font-bold text-slate-400"
            >
              =
            </span>
            <CostPart
              label="Total estimated cost"
              value={platform + owner}
              emphasis
            />
          </>
        ) : (
          <CostPart
            label={source === "platform" ? "Platform" : "Your own keys"}
            value={source === "platform" ? platform : owner}
            emphasis
          />
        )}
      </div>
      <p className="mt-2 max-w-[80ch] text-[11px] leading-relaxed text-slate-400">
        {note} This is an <b>estimate</b> for the selected period, priced at{" "}
        {tokenRate === undefined
          ? "the workspace's own token rate"
          : `$${tokenRate} per token`}{" "}
        against the tokens recorded for each model — not a bill. It excludes
        database and code-execution operations, which are not token-priced, and
        any tax, minimum or plan fee. Your provider&apos;s own invoice is the
        authority on the own-keys side.
      </p>
    </section>
  );
}

function CostPart({
  label,
  value,
  emphasis = false,
}: {
  label: string;
  value: number;
  emphasis?: boolean;
}) {
  return (
    <div className="grid gap-px">
      <span className="text-[10.5px] font-bold tracking-[0.06em] text-slate-400 uppercase">
        {label}
      </span>
      <span
        className={cn(
          "text-[19px] font-extrabold tracking-tight tabular-nums",
          emphasis ? "text-blue-600" : "text-slate-900",
        )}
      >
        {money(value)}
      </span>
    </div>
  );
}

/** A figure, and a button into its model breakdown. */
function MetricCard({
  label,
  value,
  foot,
  onOpen,
}: {
  label: string;
  value: string;
  foot: string;
  onOpen: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onOpen}
      title={`Open the model breakdown for ${label}`}
      className="flex cursor-pointer flex-col gap-0.5 rounded-xl border border-black/5 bg-white px-4 py-3 text-left shadow-sm transition-colors hover:border-blue-500 hover:bg-blue-50/60"
    >
      <span className="text-[10.5px] font-bold tracking-[0.06em] text-slate-400 uppercase">
        {label}
      </span>
      <span className="text-[21px] font-extrabold tracking-tight text-slate-900 tabular-nums">
        {value}
      </span>
      <span className="text-[10.5px] text-slate-400">{foot}</span>
    </button>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="mt-4 mb-2 text-[10px] font-bold tracking-[0.07em] text-slate-400 uppercase">
      {children}
    </p>
  );
}

function EmptyPanel({ title, body }: { title: string; body: string }) {
  return (
    <Card>
      <div className="px-6 py-11 text-center">
        <p className="text-base font-bold text-slate-900">{title}</p>
        <p className="mx-auto mt-1.5 max-w-[46ch] text-sm leading-relaxed text-slate-500">
          {body}
        </p>
      </div>
    </Card>
  );
}

/* ── the rail ───────────────────────────────────────────────────────────── */

function UsageRail({
  tab,
  onChange,
}: {
  tab: UsageTab;
  onChange: (tab: UsageTab) => void;
}) {
  return (
    <nav
      aria-label="Usage sections"
      className="mb-4 flex w-full shrink-0 flex-col gap-0.5 border-b border-slate-200 pb-2 lg:sticky lg:top-3.5 lg:mb-0 lg:w-[210px] lg:border-b-0 lg:pb-0"
    >
      <p className="px-2.5 pt-3 pb-1.5 text-[10px] font-bold tracking-[0.07em] text-slate-400 uppercase lg:pt-0">
        Usage
      </p>
      <div className="flex flex-wrap gap-0.5 lg:flex-col">
        {TABS.map((item) => {
          const active = item.key === tab;
          return (
            <button
              key={item.key}
              type="button"
              aria-current={active ? "page" : undefined}
              onClick={() => onChange(item.key)}
              className={cn(
                "relative flex cursor-pointer items-center gap-2.5 rounded-[9px] px-2.5 py-2 text-left text-sm font-semibold whitespace-nowrap transition-colors",
                active
                  ? "bg-blue-50 text-blue-600"
                  : "text-slate-600 hover:bg-slate-100 hover:text-slate-900",
              )}
            >
              {active && (
                <span className="absolute top-[7px] bottom-[7px] left-0 w-[3px] rounded-r-[3px] bg-blue-600" />
              )}
              <Icon name={USAGE_NAV_ICONS[item.key]} className="size-[15px]" />
              {item.label}
            </button>
          );
        })}
      </div>
    </nav>
  );
}

/* ── the screen ─────────────────────────────────────────────────────────── */

export default function UsageView() {
  const { agents } = useAgents();
  const [tab, setTab] = useState<UsageTab>("overview");
  const [period, setPeriod] = useState<UsagePeriod>("30d");
  const [source, setSource] = useState<UsageSource>("total");
  const [filters, setFilters] = useState<UsageFilters>({});
  const [trendMetric, setTrendMetric] = useState<TrendMetric>("total_tokens");
  const [granularity, setGranularity] = useState<UsageBucket>("day");
  const [drawer, setDrawer] = useState<DrawerSpec | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);

  /**
   * Show the top of a section when it opens.
   *
   * The sections are different lengths and the shell's `main` is the scroll
   * container, so switching from a scrolled Overview to Limits used to open the
   * new panel already scrolled past its own heading. The container is found by
   * walking up rather than named, because it belongs to the shell and this view
   * should not have to know which ancestor happens to own the scrolling.
   */
  const showSectionTop = () => {
    let node: HTMLElement | null = rootRef.current?.parentElement ?? null;
    while (node) {
      const overflow = window.getComputedStyle(node).overflowY;
      if (overflow === "auto" || overflow === "scroll") {
        node.scrollTo({ top: 0 });
        return;
      }
      node = node.parentElement;
    }
  };

  useEffect(() => {
    const syncHash = () => {
      const next = asUsageTab(window.location.hash.slice(1));
      if (next) setTab(next);
    };
    syncHash();
    window.addEventListener("hashchange", syncHash);
    return () => window.removeEventListener("hashchange", syncHash);
  }, []);

  const selectTab = (next: UsageTab) => {
    setTab(next);
    window.history.replaceState(null, "", `#${next}`);
    showSectionTop();
  };

  // The three Custom Filters controls narrow every figure on that tab, and
  // nothing on the others.
  const active: UsageFilters = tab === "filters" ? filters : {};

  const limits = useOwnerLimits();
  const tokenRate = limits.data?.token_rate_usd;

  const totals = useUsageTotals(period, source, active);
  const byOperation = useUsageAggregate(["operation"], period, source, active);
  const byLabel = useUsageAggregate(
    ["label"],
    period,
    source,
    active,
    tab === "overview",
  );
  const byModel = useUsageAggregate(
    ["model", "provider"],
    period,
    source,
    active,
    tab === "overview",
  );
  const byAgent = useUsageAggregate(
    ["agent_id"],
    period,
    source,
    active,
    tab === "agents",
  );
  const trend = useUsageTrend(period, source, granularity, active);

  // The filter options are the values the data actually has, read once per
  // period and unfiltered — a hardcoded list would go stale the moment the
  // pipeline gains a step, and offering a value with no rows behind it sends
  // the reader to an empty screen.
  const labelFacet = useUsageAggregate(
    ["label"],
    period,
    source,
    {},
    tab === "filters",
  );
  const phaseFacet = useUsageAggregate(
    ["phase"],
    period,
    source,
    {},
    tab === "filters",
  );

  const selected = totals.data?.selected;
  const periodText = periodLabelFor(period);
  const sourceText =
    USAGE_SOURCE_OPTIONS.find((option) => option.value === source)?.label ??
    source;

  const metricValue = (key: AccountMetricKey): number =>
    key === "requests" ? (selected?.requests ?? 0) : (selected?.[key] ?? 0);

  const openDrawer = (
    title: string,
    metric: AccountMetricKey,
    extra: UsageFilters = {},
    scope = `${periodText} · ${sourceText}`,
  ) => setDrawer({ title, metric, filters: { ...active, ...extra }, scope });

  const nameFor = (agentId: string) =>
    agents.find((agent) => agent.agent_id === agentId)?.name ?? agentId;

  const headerTitle =
    tab === "overview" || tab === "limits"
      ? "Account Overview"
      : (TABS.find((item) => item.key === tab)?.label ?? "Usage");

  const baseSub =
    "Token and service consumption across every database agent in your workspace, with the cost each one adds up to.";
  const headerDescription =
    tab === "limits"
      ? "What this workspace is allowed to use, and how much of it has been used. The consumption-source filter does not apply here — a limit is enforced against what the platform served, whichever key paid for it."
      : source === "platform"
        ? `${baseSub} Showing PLATFORM CONSUMPTIONS only — work billed to FutureSmart platform keys.`
        : source === "owner"
          ? `${baseSub} Showing OWNER CONSUMPTIONS only — work billed to your own provider credentials.`
          : `${baseSub} Showing TOTAL CONSUMPTIONS — platform plus your own keys.`;

  const limitsTab = tab === "limits";

  /* ── overview pieces ─────────────────────────────────────────────────── */

  // Memoised because the service-breakdown segments below derive from it: a
  // fresh `?? []` each render would rebuild them every time.
  const operationGroups = useMemo(
    () => byOperation.data?.groups ?? [],
    [byOperation.data],
  );
  const operationCount = (operation: string): number =>
    operationGroups
      .filter((group) => group.operation === operation)
      .reduce((sum, group) => sum + (group.event_count ?? 0), 0);

  const serviceSegments = useMemo(
    () =>
      operationGroups
        .map((group, index) => ({
          name: group.operation ?? "unattributed",
          value: group.event_count ?? 0,
          color: SERIES[index % SERIES.length],
        }))
        .filter((segment) => segment.value > 0)
        .sort((a, b) => b.value - a.value),
    [operationGroups],
  );
  const serviceTotal = serviceSegments.reduce(
    (sum, segment) => sum + segment.value,
    0,
  );

  const modelRows = useMemo(() => {
    const groups = byModel.data?.groups ?? [];
    return {
      rows: groups
        .filter((group) => group.model)
        .map((group) => ({
          model: group.model as string,
          provider: group.provider ?? "—",
          requests: group.event_count ?? 0,
          input: metricTotal(group, "input_tokens"),
          output: metricTotal(group, "output_tokens"),
          total: metricTotal(group, "total_tokens"),
        }))
        .sort((a, b) => b.total - a.total),
      modelless: groups
        .filter((group) => !group.model)
        .reduce((sum, group) => sum + (group.event_count ?? 0), 0),
    };
  }, [byModel.data]);

  const nodeRows = useMemo(() => {
    const groups = (byLabel.data?.groups ?? []).filter((group) => group.label);
    const totalCalls = groups.reduce(
      (sum, group) => sum + (group.event_count ?? 0),
      0,
    );
    const totalTokens = groups.reduce(
      (sum, group) => sum + metricTotal(group, "total_tokens"),
      0,
    );
    return groups
      .map((group) => {
        const calls = group.event_count ?? 0;
        const tokens = metricTotal(group, "total_tokens");
        const seconds = metricAvg(group, "execution_time_seconds");
        return {
          label: group.label as string,
          calls,
          frequency: totalCalls ? (calls / totalCalls) * 100 : 0,
          latency: seconds === undefined ? null : seconds * 1000,
          avgCost: calls ? tokenCost(tokens, tokenRate) / calls : 0,
          costShare: totalTokens ? (tokens / totalTokens) * 100 : 0,
          avgInput: metricAvg(group, "input_tokens") ?? 0,
          avgOutput: metricAvg(group, "output_tokens") ?? 0,
        };
      })
      .sort((a, b) => b.calls - a.calls);
  }, [byLabel.data, tokenRate]);

  const agentRows = useMemo(() => {
    const groups = byAgent.data?.groups ?? [];
    return {
      rows: groups
        .filter((group) => group.agent_id)
        .map((group) => ({
          agentId: group.agent_id as string,
          requests: group.event_count ?? 0,
          input: metricTotal(group, "input_tokens"),
          output: metricTotal(group, "output_tokens"),
          total: metricTotal(group, "total_tokens"),
        }))
        .sort((a, b) => b.total - a.total),
      // `agent_id: null` is real: some operations are recorded against the
      // workspace rather than an agent. Counting them here is what stops this
      // table reporting nothing while the Overview reports requests — two
      // screens disagreeing about the same period is worse than a footnote.
      unattributed: groups
        .filter((group) => !group.agent_id)
        .reduce((sum, group) => sum + (group.event_count ?? 0), 0),
    };
  }, [byAgent.data]);

  const facetOptions = (
    groups: AggregateGroup[] | undefined,
    key: "label" | "phase",
    allLabel: string,
  ) => [
    { value: "", label: allLabel },
    ...[
      ...new Set(
        (groups ?? [])
          .map((group) => group[key])
          .filter((value): value is string => Boolean(value)),
      ),
    ]
      .sort()
      .map((value) => ({ value, label: value })),
  ];

  const hasFilteredUsage = (selected?.requests ?? 0) > 0;

  const accountCards = (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {ACCOUNT_METRICS.map((metric) => (
        <MetricCard
          key={metric.key}
          label={metric.label}
          value={nfmt(metricValue(metric.key))}
          foot={metric.foot}
          onOpen={() => openDrawer(metric.label, metric.key)}
        />
      ))}
    </div>
  );

  const trendCard = (
    <UsageTrendChart
      series={trend.data?.series ?? []}
      metric={trendMetric}
      onMetricChange={setTrendMetric}
      granularity={granularity}
      onGranularityChange={setGranularity}
      tokenRate={tokenRate}
      periodLabel={periodText}
      sourceLabel={sourceText}
      isLoading={trend.isLoading}
    />
  );

  const donutCard = (
    <Card>
      <CardHeader
        title="Service Breakdown"
        note={`share of billed operations · ${periodText} · ${sourceText}`}
      />
      <CardBody>
        {serviceSegments.length ? (
          <div className="flex flex-nowrap items-center gap-5">
            <div className="shrink-0">
              <Donut
                segments={serviceSegments}
                center={String(serviceSegments.length)}
              />
            </div>
            <div className="min-w-0 flex-1 space-y-1.5">
              {serviceSegments.map((segment) => (
                <div
                  key={segment.name}
                  className="flex items-center gap-2 text-xs"
                >
                  <span
                    className="size-2.5 shrink-0 rounded-sm"
                    style={{ background: segment.color }}
                  />
                  <span className="min-w-0 flex-1 truncate text-slate-600">
                    {segment.name}
                  </span>
                  <span className="font-bold tabular-nums text-slate-900">
                    {((segment.value / serviceTotal) * 100).toFixed(1)}%
                  </span>
                  <span className="min-w-14 text-right tabular-nums text-slate-400">
                    {nfmt(segment.value)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <div className="py-8 text-center">
            <p className="text-base font-bold text-slate-900">
              Nothing to break down
            </p>
            <p className="mt-1.5 text-sm text-slate-500">
              No operation recorded any activity in this window.
            </p>
          </div>
        )}
      </CardBody>
    </Card>
  );

  return (
    // The page mounts this `flush`, so there is no shell padding to cancel with
    // a negative margin and the parent has a definite height for `min-h-full`
    // to resolve against — the canvas now fills the scroll container on a short
    // tab instead of stopping where the content does.
    <div ref={rootRef} className="min-h-full bg-slate-50 px-6 py-7 lg:px-10">
      <header className="mb-6">
        <Link
          href={ROUTES.home}
          className="inline-flex w-fit items-center gap-1.5 text-[13px] font-semibold text-slate-600 hover:text-blue-600"
        >
          <Icon name="back" className="size-3.5" />
          Back to Home
        </Link>
        <div className="mt-4 flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-slate-900">
              {headerTitle}
            </h1>
            <p className="mt-1 max-w-3xl text-sm leading-relaxed text-slate-500">
              {headerDescription}
            </p>
          </div>
          <div className="grid shrink-0 gap-3 sm:grid-cols-2">
            <Field
              label={
                limitsTab
                  ? "Consumption source (not applied to Limits)"
                  : "Consumption source"
              }
              className="min-w-52"
            >
              <Select
                aria-label="Consumption source"
                value={source}
                disabled={limitsTab}
                title={
                  limitsTab
                    ? "Not applied on the Limits tab — a limit counts every request, whichever key paid for it"
                    : "Applies to every figure on this screen"
                }
                onChange={(value) => setSource(value as UsageSource)}
                options={USAGE_SOURCE_OPTIONS}
              />
            </Field>
            <Field
              label={limitsTab ? "Period (fixed on Limits)" : "Period"}
              className="min-w-44"
            >
              <Select
                aria-label="Usage period"
                value={period}
                disabled={limitsTab}
                title={
                  limitsTab
                    ? "Not applied on the Limits tab — a limit runs on its own billing window"
                    : "Applies to every figure on this screen"
                }
                onChange={(value) => setPeriod(value as UsagePeriod)}
                options={USAGE_PERIOD_OPTIONS}
              />
            </Field>
          </div>
        </div>
      </header>

      {/*
        `items-start` keeps the sticky rail from stretching in the row layout,
        but on the column axis it also lets a child shrink-to-fit — and the
        widest table then sized this column to itself and scrolled the whole
        shell sideways. Both children are explicitly full width, so a wide
        table scrolls inside its own `overflow-auto` wrapper instead.
      */}
      <div className="flex flex-col items-start gap-5 lg:flex-row">
        <UsageRail tab={tab} onChange={selectTab} />
        <main className="w-full min-w-0 max-w-282.5 flex-1 lg:w-auto">
          {tab === "overview" && (
            <div>
              <CostStrip
                platformTokens={totals.data?.platform.total_tokens ?? 0}
                ownerTokens={totals.data?.owner.total_tokens ?? 0}
                tokenRate={tokenRate}
                source={source}
                sourceLabel={sourceText}
                periodLabel={periodText}
              />

              {hasFilteredUsage ? (
                accountCards
              ) : (
                <EmptyPanel
                  title={`Nothing recorded for ${sourceText}`}
                  body={`No usage was billed to this source in ${periodText.toLowerCase()}. Switch the consumption source back to Total, or widen the period.`}
                />
              )}

              <SectionLabel>Databases</SectionLabel>
              <div className="grid gap-3 sm:grid-cols-2">
                {SERVICE_OPERATIONS.map((service) => (
                  <MetricCard
                    key={service.operation}
                    label={service.label}
                    value={nfmt(operationCount(service.operation))}
                    foot={service.foot}
                    onOpen={() =>
                      openDrawer(service.label, "requests", {
                        operation: service.operation,
                      })
                    }
                  />
                ))}
              </div>

              <div className="mt-4 space-y-4">
                {trendCard}
                {donutCard}

                <Card className="overflow-hidden">
                  <CardHeader
                    title="Usage by Model"
                    note={`every model that served a request · ${periodText} · ${sourceText}`}
                  />
                  <div className={TABLE.wrap}>
                    <table className={TABLE.table}>
                      <thead>
                        <tr className={TABLE.headRow}>
                          {[
                            "Model",
                            "Provider",
                            "Requests",
                            "Input Tokens",
                            "Output Tokens",
                            "Total Tokens",
                            "Cost",
                          ].map((head, index) => (
                            <th
                              key={head}
                              className={index < 2 ? TABLE.th : TABLE.thNumeric}
                            >
                              {head}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {modelRows.rows.length ? (
                          modelRows.rows.map((row) => (
                            <tr
                              key={`${row.provider}/${row.model}`}
                              className={TABLE.row}
                            >
                              <td
                                className={cn(
                                  TABLE.td,
                                  "font-mono text-[11.5px] font-bold text-slate-800",
                                )}
                              >
                                {row.model}
                              </td>
                              <td className={TABLE.td}>{row.provider}</td>
                              <td className={TABLE.tdNumeric}>
                                {nfmt(row.requests)}
                              </td>
                              <td className={TABLE.tdNumeric}>
                                {nfmt(row.input)}
                              </td>
                              <td className={TABLE.tdNumeric}>
                                {nfmt(row.output)}
                              </td>
                              <td
                                className={cn(TABLE.tdNumeric, "font-semibold")}
                              >
                                {nfmt(row.total)}
                              </td>
                              <td
                                className={cn(
                                  TABLE.tdNumeric,
                                  "text-emerald-600",
                                )}
                              >
                                {money(tokenCost(row.total, tokenRate))}
                              </td>
                            </tr>
                          ))
                        ) : (
                          <tr>
                            <td
                              colSpan={7}
                              className="px-4 py-10 text-center text-sm text-slate-400"
                            >
                              No model usage in this window.
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                  {modelRows.modelless > 0 && (
                    <p className="border-t border-slate-100 px-4 py-2.5 text-[11px] text-slate-400">
                      A further {nfmt(modelRows.modelless)} operations ran
                      without a model — database queries and code executions are
                      recorded with no model or provider, so they are counted in
                      the figures above but cannot be listed here.
                    </p>
                  )}
                </Card>

                <Card className="overflow-hidden">
                  <CardHeader
                    title="Per-Node Breakdown"
                    note={`token & cost share by pipeline step · ${periodText} · ${sourceText}`}
                  />
                  <div className={TABLE.wrap}>
                    <table className={TABLE.table}>
                      <thead>
                        <tr className={TABLE.headRow}>
                          {[
                            "Node",
                            "Calls",
                            "Frequency",
                            "Avg Latency",
                            "Avg Cost",
                            "% of Cost",
                            "Avg In Tok",
                            "Avg Out Tok",
                          ].map((head, index) => (
                            <th
                              key={head}
                              className={
                                index === 0 ? TABLE.th : TABLE.thNumeric
                              }
                            >
                              {head}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {nodeRows.length ? (
                          nodeRows.map((row) => (
                            <tr key={row.label} className={TABLE.row}>
                              <td
                                className={cn(
                                  TABLE.td,
                                  "font-semibold text-slate-800",
                                )}
                              >
                                {row.label}
                              </td>
                              <td className={TABLE.tdNumeric}>
                                {nfmt(row.calls)}
                              </td>
                              <td className={TABLE.tdNumeric}>
                                {row.frequency.toFixed(0)}%
                              </td>
                              <td className={TABLE.tdNumeric}>
                                {row.latency === null ? "—" : ms(row.latency)}
                              </td>
                              <td className={TABLE.tdNumeric}>
                                ${row.avgCost.toFixed(5)}
                              </td>
                              <td className={TABLE.tdNumeric}>
                                {row.costShare.toFixed(0)}%
                              </td>
                              <td className={TABLE.tdNumeric}>
                                {nfmt(Math.round(row.avgInput))}
                              </td>
                              <td className={TABLE.tdNumeric}>
                                {nfmt(Math.round(row.avgOutput))}
                              </td>
                            </tr>
                          ))
                        ) : (
                          <tr>
                            <td
                              colSpan={8}
                              className="px-4 py-10 text-center text-sm text-slate-400"
                            >
                              No pipeline steps recorded in this window.
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </Card>
              </div>
            </div>
          )}

          {tab === "limits" && <PlanLimits />}

          {tab === "agents" && (
            <div>
              <CostStrip
                platformTokens={totals.data?.platform.total_tokens ?? 0}
                ownerTokens={totals.data?.owner.total_tokens ?? 0}
                tokenRate={tokenRate}
                source={source}
                sourceLabel={sourceText}
                periodLabel={periodText}
              />
              <Card className="overflow-hidden">
                <CardHeader
                  title="Agents"
                  note={`per-agent consumption · ${periodText} · ${sourceText} · pick a row for its model breakdown`}
                />
                <div className={TABLE.wrap}>
                  <table className={TABLE.table}>
                    <thead>
                      <tr className={TABLE.headRow}>
                        {[
                          "Agent",
                          "Agent ID",
                          "Requests",
                          "Input Tokens",
                          "Output Tokens",
                          "Total Tokens",
                          "Cost",
                        ].map((head, index) => (
                          <th
                            key={head}
                            className={index < 2 ? TABLE.th : TABLE.thNumeric}
                          >
                            {head}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {agentRows.rows.length ? (
                        agentRows.rows.map((row) => (
                          <tr
                            key={row.agentId}
                            className={cn(TABLE.row, "cursor-pointer")}
                            tabIndex={0}
                            title={`Breakdown by model and provider · ${nameFor(row.agentId)}`}
                            onClick={() =>
                              openDrawer(
                                "Total Tokens",
                                "total_tokens",
                                { agent_id: row.agentId },
                                `${nameFor(row.agentId)} · ${sourceText}`,
                              )
                            }
                            onKeyDown={(event) => {
                              if (event.key === "Enter" || event.key === " ") {
                                event.preventDefault();
                                openDrawer(
                                  "Total Tokens",
                                  "total_tokens",
                                  { agent_id: row.agentId },
                                  `${nameFor(row.agentId)} · ${sourceText}`,
                                );
                              }
                            }}
                          >
                            <td className={TABLE.td}>
                              <span className="flex items-center gap-2">
                                <span className="flex size-6.5 items-center justify-center rounded-[7px] bg-blue-50 text-blue-600">
                                  <Icon name="db" className="size-3.5" />
                                </span>
                                <b className="font-semibold text-slate-800">
                                  {nameFor(row.agentId)}
                                </b>
                              </span>
                            </td>
                            <td
                              className={cn(
                                TABLE.td,
                                "font-mono text-[11px] text-slate-400",
                              )}
                            >
                              {row.agentId}
                            </td>
                            <td className={TABLE.tdNumeric}>
                              {nfmt(row.requests)}
                            </td>
                            <td className={TABLE.tdNumeric}>
                              {nfmt(row.input)}
                            </td>
                            <td className={TABLE.tdNumeric}>
                              {nfmt(row.output)}
                            </td>
                            <td
                              className={cn(TABLE.tdNumeric, "font-semibold")}
                            >
                              {nfmt(row.total)}
                            </td>
                            <td
                              className={cn(
                                TABLE.tdNumeric,
                                "text-emerald-600",
                              )}
                            >
                              {money(tokenCost(row.total, tokenRate))}
                            </td>
                          </tr>
                        ))
                      ) : (
                        <tr>
                          <td
                            colSpan={7}
                            className="px-4 py-10 text-center text-sm text-slate-400"
                          >
                            No agent usage recorded in this window.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
                {agentRows.unattributed > 0 && (
                  <p className="border-t border-slate-100 px-4 py-2.5 text-[11px] text-slate-400">
                    A further {nfmt(agentRows.unattributed)} operations were
                    recorded against the workspace rather than a single agent —
                    they are counted in the account figures but cannot be
                    attributed to a row here.
                  </p>
                )}
              </Card>
            </div>
          )}

          {tab === "filters" && (
            <div>
              <CostStrip
                platformTokens={totals.data?.platform.total_tokens ?? 0}
                ownerTokens={totals.data?.owner.total_tokens ?? 0}
                tokenRate={tokenRate}
                source={source}
                sourceLabel={sourceText}
                periodLabel={periodText}
              />

              <Card className="mb-4">
                <CardHeader
                  title="Custom Filters"
                  note={`narrow the account view to one slice of usage · ${sourceText}`}
                />
                {/*
                  No Service facet. Every row this product records is `nl2sql`,
                  so `group_by=service_type` is a 422 rather than a single group
                  — the control that used to sit here asked the service a
                  question it refuses to answer. Operation is the finer cut and
                  stays.
                */}
                <CardBody className="grid gap-3 sm:grid-cols-3">
                  <Field label="Agent">
                    <Select
                      aria-label="Filter by agent"
                      value={filters.agent_id ?? ""}
                      onChange={(value) =>
                        setFilters((current) => ({
                          ...current,
                          agent_id: (value as string) || undefined,
                        }))
                      }
                      options={[
                        { value: "", label: "All agents" },
                        ...agents.map((agent) => ({
                          value: agent.agent_id,
                          label: agent.name,
                        })),
                      ]}
                    />
                  </Field>
                  <Field label="Operation">
                    <Select
                      aria-label="Filter by operation"
                      value={filters.label ?? ""}
                      onChange={(value) =>
                        setFilters((current) => ({
                          ...current,
                          label: (value as string) || undefined,
                        }))
                      }
                      options={facetOptions(
                        labelFacet.data?.groups,
                        "label",
                        "All operations",
                      )}
                    />
                  </Field>
                  <Field label="Functional Label">
                    <Select
                      aria-label="Filter by functional label"
                      value={filters.phase ?? ""}
                      onChange={(value) =>
                        setFilters((current) => ({
                          ...current,
                          phase: (value as string) || undefined,
                        }))
                      }
                      options={facetOptions(
                        phaseFacet.data?.groups,
                        "phase",
                        "All labels",
                      )}
                    />
                  </Field>
                </CardBody>
              </Card>

              {hasFilteredUsage ? (
                <div className="space-y-4">
                  {accountCards}
                  {trendCard}
                  {donutCard}
                </div>
              ) : (
                <Card>
                  <div className="px-6 py-11 text-center">
                    <span className="mx-auto mb-3 flex size-13 items-center justify-center rounded-[15px] bg-blue-50 text-blue-600">
                      <Icon name="search" className="size-6" />
                    </span>
                    <p className="text-base font-bold text-slate-900">
                      No usage matches these filters.
                    </p>
                    <p className="mx-auto mt-1.5 max-w-[46ch] text-sm leading-relaxed text-slate-500">
                      Nothing was billed against this combination in{" "}
                      {periodText.toLowerCase()} under {sourceText}. Widen one
                      of the three filters, change the consumption source, or
                      clear the filters and start again.
                    </p>
                    <button
                      type="button"
                      onClick={() => setFilters({})}
                      className="mt-4 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm font-semibold text-slate-700 shadow-sm hover:bg-slate-50"
                    >
                      Clear filters
                    </button>
                  </div>
                </Card>
              )}
            </div>
          )}
        </main>
      </div>

      {drawer && (
        <BreakdownDrawer
          spec={drawer}
          period={period}
          source={source}
          periodLabel={periodText}
          sourceLabel={sourceText}
          tokenRate={tokenRate}
          onClose={() => setDrawer(null)}
        />
      )}
    </div>
  );
}
