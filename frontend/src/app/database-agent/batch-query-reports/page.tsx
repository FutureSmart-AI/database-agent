"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";

import ReportsView from "@/components/reports/ReportsView";
import AgentScope from "@/components/shell/AgentScope";
import AppShell from "@/components/shell/AppShell";
import { ROUTES } from "@/lib/routes";

function Reports() {
  const agentId = useSearchParams().get("agentId") ?? undefined;
  return (
    <AppShell agentId={agentId}>
      <AgentScope
        agentId={agentId}
        route={ROUTES.reports}
        purpose="A batch report runs a set of questions against one agent. Pick the agent to report on."
      >
        <ReportsView agentId={agentId} />
      </AgentScope>
    </AppShell>
  );
}

export default function BatchQueryReportsPage() {
  return (
    <Suspense>
      <Reports />
    </Suspense>
  );
}
