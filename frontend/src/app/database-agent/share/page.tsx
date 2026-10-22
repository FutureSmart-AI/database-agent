"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";

import ShareView from "@/components/share/ShareView";
import AgentScope from "@/components/shell/AgentScope";
import AppShell from "@/components/shell/AppShell";
import { ROUTES } from "@/lib/routes";

function Share() {
  const agentId = useSearchParams().get("agentId") ?? undefined;
  return (
    <AppShell agentId={agentId}>
      <AgentScope
        agentId={agentId}
        route={ROUTES.share}
        purpose="Share links, embed snippets and API keys belong to one agent. Pick the agent you want to share."
      >
        <ShareView agentId={agentId} />
      </AgentScope>
    </AppShell>
  );
}

export default function SharePage() {
  return (
    <Suspense>
      <Share />
    </Suspense>
  );
}
