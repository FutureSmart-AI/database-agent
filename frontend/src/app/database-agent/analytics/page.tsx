"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";

import AnalyticsView from "@/components/analytics/AnalyticsView";
import FleetOverview from "@/components/analytics/FleetOverview";
import AgentScope from "@/components/shell/AgentScope";
import AppShell from "@/components/shell/AppShell";
import { ROUTES } from "@/lib/routes";

/**
 * Analytics — the agent UI's analytics page, on the NL2SQL service's own reads.
 *
 * The page itself is shared, not copied: `AnalyticsView` mounts the dashboard's
 * toolbar, tabs, charts and tables and only swaps the endpoints underneath them.
 * The dashboard's `/api/dashboard/v1/agents/{id}/scorecard|trends|queries` are
 * keyed by chat-registry ids and answer 403 for an `NL2SQL_…` agent — which is
 * why this screen once rendered "—" in every KPI — while the NL2SQL service
 * serves the same shapes at `/nl2sql/api/v1/agents/{id}/analytics/…`.
 */
function Analytics() {
  const agentId = useSearchParams().get("agentId") ?? undefined;

  /**
   * No agent asked for: the fleet grid, not a bare picker.
   *
   * `/v1/agents/analytics/overview` answers "which agent is failing, which is
   * expensive" in one call, and every row links into that agent's screen — so
   * the landing state both chooses an agent and says which one is worth
   * opening. The picker stays as the fallback for a workspace where nothing
   * has been asked yet, since the grid would have no rows to show.
   */
  if (!agentId) {
    return (
      <AppShell>
        <FleetOverview
          fallback={
            <AgentScope
              route={ROUTES.analytics}
              purpose="Analytics cover one agent's questions, cost and latency. Pick the agent you want to look at — workspace-wide totals live under Usage."
            >
              {null}
            </AgentScope>
          }
        />
      </AppShell>
    );
  }

  return (
    <AppShell agentId={agentId}>
      <AnalyticsView agentId={agentId} />
    </AppShell>
  );
}

export default function AnalyticsPage() {
  return (
    <Suspense>
      <Analytics />
    </Suspense>
  );
}
