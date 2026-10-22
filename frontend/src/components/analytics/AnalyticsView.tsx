"use client";

import { useMemo, type ComponentType } from "react";
import dynamic from "next/dynamic";

import type { UseQueryResult } from "@tanstack/react-query";

import { Card } from "@/components/ui/Card";
import EmptyState from "@/components/ui/EmptyState";
import { APIS } from "@/data/api";
import { useAgent } from "@/data/useAgents";
import {
  adaptQueryLog,
  adaptScorecard,
  adaptTrends,
  trendsWindowParams,
} from "@/lib/analyticsAdapters";
import {
  NL2SQL_FILTER_OPTIONS,
  NL2SQL_LIMITS,
} from "@/lib/analyticsContractOptions";
import { AnalyticsScopeProvider } from "@/platform/analytics/AnalyticsScope";
import AnalyticsToolbar from "@/platform/analytics/components/AnalyticsToolbar";
import NoAnalyticsYetBanner from "@/platform/analytics/components/NoAnalyticsYetBanner";
import TabNav from "@/platform/analytics/components/TabNav";
import { useAnalyticsWindow } from "@/platform/analytics/hooks/useAnalyticsWindow";
import { useScorecard } from "@/platform/analytics/hooks/useScorecard";
import {
  computeScorecardDeltas,
  type ScorecardDeltas,
} from "@/platform/analytics/lib/scorecardDeltas";
import type { AnalyticsWindow, Scorecard } from "@/platform/analytics/types";
import {
  buildPreviousWindow,
  emptyScorecard,
  getHttpStatus,
} from "@/platform/analytics/utils";

import { NL2SQL_ANALYTICS_TABS, type Nl2sqlTabKey } from "./constants";

/**
 * One agent's analytics — the agent dashboard's analytics page, on NL2SQL data.
 *
 * Not a copy of that page: the toolbar, tab bar, KPI cards, charts and tables
 * are the dashboard's own components, imported from
 * `src/app/dashboard/analytics`. Only the endpoints differ, and those are
 * injected through `AnalyticsScopeProvider` — the dashboard's
 * `/api/dashboard/v1/agents/{id}/scorecard|trends|queries` are keyed by
 * chat-registry ids and answer 403 for an `NL2SQL_…` agent, while the NL2SQL
 * service serves the same shapes at `/nl2sql/api/v1/agents/{id}/analytics/…`.
 * Because the components are shared rather than duplicated, the two screens
 * cannot drift apart again.
 *
 * The one addition is a sixth tab, Failures, which has no dashboard equivalent
 * because no other product can fail by generating SQL a database rejects.
 */

const OverviewTab = dynamic(
  () => import("@/platform/analytics/components/tabs/OverviewTab"),
  { ssr: false },
);
const QualityTab = dynamic(
  () => import("@/platform/analytics/components/tabs/QualityTab"),
  { ssr: false },
);
const PerformanceTab = dynamic(
  () => import("@/platform/analytics/components/tabs/PerformanceTab"),
  { ssr: false },
);
const CostTab = dynamic(
  () => import("@/platform/analytics/components/tabs/CostTab"),
  { ssr: false },
);
const QueryLogsTab = dynamic(
  () => import("@/platform/analytics/components/tabs/QueryLogsTab"),
  { ssr: false },
);
const FailuresTab = dynamic(() => import("./tabs/FailuresTab"), { ssr: false });

type TabProps = {
  scorecard: UseQueryResult<Scorecard>;
  window: AnalyticsWindow;
  agentId?: string | null;
  onTabChange?: (tab: Nl2sqlTabKey) => void;
  deltas?: ScorecardDeltas;
};

const tabComponents: Record<Nl2sqlTabKey, ComponentType<TabProps>> = {
  overview: OverviewTab as ComponentType<TabProps>,
  quality: QualityTab as ComponentType<TabProps>,
  performance: PerformanceTab as ComponentType<TabProps>,
  cost: CostTab as ComponentType<TabProps>,
  failures: FailuresTab as ComponentType<TabProps>,
  querylogs: QueryLogsTab as ComponentType<TabProps>,
};

/**
 * Endpoint templates and response adapters for the scope.
 *
 * Module-level constants, not values built in the component: the provider
 * memoizes on their identity, so fresh objects each render would rebuild the
 * context — and everything reading from it — on every state change.
 */
const NL2SQL_ANALYTICS_APIS = {
  SCORECARD: APIS.ANALYTICS_SCORECARD,
  TRENDS: APIS.ANALYTICS_TRENDS,
  QUERIES: APIS.ANALYTICS_QUERIES,
  SYNC_COSTS: APIS.ANALYTICS_SYNC_COSTS,
} as const;

const NL2SQL_ANALYTICS_ADAPTERS = {
  scorecard: adaptScorecard,
  trends: adaptTrends,
  queries: adaptQueryLog,
} as const;

/**
 * Only `trends` differs: `scorecard`, `queries` and `failures` all take the
 * rolling `period` / `start_date` + `end_date` pair the dashboard already sends.
 */
const NL2SQL_WINDOW_PARAMS = { trends: trendsWindowParams } as const;

const TAB_KEYS = NL2SQL_ANALYTICS_TABS.map((tab) => tab.key);

interface AnalyticsViewProps {
  agentId?: string;
}

function AnalyticsScreen({ serviceId }: { serviceId: string }) {
  const { window, setWindow, activeTab, setTab, bucket, setBucket } =
    useAnalyticsWindow<Nl2sqlTabKey>(TAB_KEYS);
  const scorecard = useScorecard(serviceId, window, { bucket });

  // Second scorecard for the previous period so every KPI card can show a
  // "vs prev period" pill. Until the current one resolves the previous window is
  // unknown, so this falls back to `window` — same query key, no extra request.
  const prevWindow = useMemo(
    () => buildPreviousWindow(scorecard.data),
    [scorecard.data],
  );
  const prevScorecard = useScorecard(serviceId, prevWindow ?? window, {
    bucket,
  });
  const deltas = useMemo(
    () =>
      prevWindow
        ? computeScorecardDeltas(scorecard.data, prevScorecard.data)
        : undefined,
    [prevWindow, scorecard.data, prevScorecard.data],
  );

  // The toolbar's "vs …" label comes from the window the deltas were actually
  // computed against, not from `trends.comparison`. The API's comparison window
  // is its own, and labelling one span while the pills measure another is how a
  // reader gets a wrong answer from a correct number.
  const previousSince =
    prevWindow?.mode === "custom" ? prevWindow.start : undefined;

  // A brand-new agent 404s on four of the six routes — the documented first-run
  // state, not an error. Render the full page with every metric at 0 so the
  // layout is the same on day one as on day thirty.
  const isNoData = scorecard.isError && getHttpStatus(scorecard.error) === 404;
  const scorecardForTabs = (
    isNoData
      ? {
          ...scorecard,
          data: emptyScorecard(serviceId, window),
          isError: false,
          isLoading: false,
          isSuccess: true,
          status: "success",
        }
      : scorecard
  ) as UseQueryResult<Scorecard>;

  const ActiveTab = tabComponents[activeTab];

  return (
    <>
      {/*
       * No PageHeader, deliberately: the agent dashboard's analytics page opens
       * straight onto its window bar, and `AppShell` already titles this screen
       * in the topbar `h1`. A second heading would both push the tabs down out
       * of parity and give the page two `h1`s.
       */}
      <AnalyticsToolbar
        window={window}
        onWindowChange={setWindow}
        since={scorecardForTabs.data?.since}
        until={scorecardForTabs.data?.until}
        previousSince={previousSince}
        bucket={bucket}
        onBucketChange={setBucket}
      />

      <div className="pt-4">
        <TabNav<Nl2sqlTabKey>
          tabs={NL2SQL_ANALYTICS_TABS}
          activeTab={activeTab}
          onChange={setTab}
        />
      </div>

      {isNoData && (
        <div className="pt-4">
          <NoAnalyticsYetBanner />
        </div>
      )}

      <div className="pt-4">
        <ActiveTab
          scorecard={scorecardForTabs}
          window={window}
          agentId={serviceId}
          onTabChange={setTab}
          deltas={deltas}
        />
      </div>
    </>
  );
}

export default function AnalyticsView({ agentId }: AnalyticsViewProps) {
  const { agent, isLoading: agentLoading } = useAgent(agentId);

  // Analytics is keyed by the NL2SQL `agent_id` — `service_ref`, not the id in
  // the URL — so the screen waits for the agent record rather than firing six
  // requests against an id the analytics service has never seen.
  if (!agent?.service_ref) {
    return (
      <Card>
        <EmptyState
          icon={agentLoading ? "ref" : "warn"}
          title={agentLoading ? "Loading this agent…" : "No database agent"}
        />
      </Card>
    );
  }

  return (
    <AnalyticsScopeProvider
      apis={NL2SQL_ANALYTICS_APIS}
      adapt={NL2SQL_ANALYTICS_ADAPTERS}
      windowParams={NL2SQL_WINDOW_PARAMS}
      filterOptions={NL2SQL_FILTER_OPTIONS}
      limits={NL2SQL_LIMITS}
    >
      <AnalyticsScreen serviceId={agent.service_ref} />
    </AnalyticsScopeProvider>
  );
}
