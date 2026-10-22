"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";

import SettingsView from "@/components/settings/SettingsView";
import AgentScope from "@/components/shell/AgentScope";
import AppShell from "@/components/shell/AppShell";
import { ROUTES } from "@/lib/routes";

function Settings() {
  const agentId = useSearchParams().get("agentId") ?? undefined;
  return (
    <AppShell agentId={agentId}>
      <AgentScope
        agentId={agentId}
        route={ROUTES.settings}
        purpose="Databases, answers and advanced options are configured per agent. Pick the agent you want to configure."
      >
        <SettingsView agentId={agentId} />
      </AgentScope>
    </AppShell>
  );
}

export default function SettingsPage() {
  return (
    <Suspense>
      <Settings />
    </Suspense>
  );
}
