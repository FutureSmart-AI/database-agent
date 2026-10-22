"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";

import Nl2sqlChatView from "@/components/conversations/Nl2sqlChatView";
import AgentScope from "@/components/shell/AgentScope";
import AppShell from "@/components/shell/AppShell";
import AuthBridge from "@/data/AuthBridge";
import { ROUTES } from "@/lib/routes";

function Conversations() {
  const agentId = useSearchParams().get("agentId") ?? undefined;
  return (
    // The thread and the conversation list own their own scrolling, so the shell
    // hands them the full viewport instead of the padded view box — but only once
    // an agent is open; the picker is an ordinary padded view.
    <AppShell agentId={agentId} flush={Boolean(agentId)}>
      <AgentScope
        agentId={agentId}
        route={ROUTES.conversations}
        purpose="Conversations are the questions asked of one agent. Pick the agent you want to open."
      >
        {/* The thread reuses the agent UI's chat stream, feedback and speech
            components, so it reads its agent and viewer from that app's auth
            context rather than from props. */}
        <AuthBridge agentId={agentId}>
          <Nl2sqlChatView />
        </AuthBridge>
      </AgentScope>
    </AppShell>
  );
}

export default function ConversationsPage() {
  return (
    <Suspense>
      <Conversations />
    </Suspense>
  );
}
