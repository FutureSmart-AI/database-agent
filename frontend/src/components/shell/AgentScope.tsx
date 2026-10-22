"use client";

import { useRouter } from "next/navigation";

import Icon from "@/components/Icon";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import Chip from "@/components/ui/Chip";
import EmptyState from "@/components/ui/EmptyState";
import PageHeader from "@/components/ui/PageHeader";
import { AgentPickerSkeleton } from "@/components/ui/Skeletons";
import { useAgents, useSharedAgents } from "@/data/useAgents";
import { apiMessage } from "@/lib/apiError";
import { agentRoute, ROUTES } from "@/lib/routes";

type Route = (typeof ROUTES)[keyof typeof ROUTES];

interface AgentScopeProps {
  /** The agent asked for in the URL, if any. */
  agentId?: string;
  /** The route to come back to once an agent has been picked. */
  route: Route;
  /** What this view needs an agent for, shown above the picker. */
  purpose: string;
  children: React.ReactNode;
}

/**
 * Guards the agent-scoped views.
 *
 * Reached without `?agentId=` — from a bookmark, or from Home's workspace-level
 * cards — these views used to quietly show the first agent in the workspace,
 * which read as an agent being selected when none was. They now ask which agent
 * you mean instead.
 */
export default function AgentScope({
  agentId,
  route,
  purpose,
  children,
}: AgentScopeProps) {
  const router = useRouter();
  // The picker's cards count each agent's databases, but the picker only exists
  // when no agent was asked for — inside one, the list is read for nothing.
  const { agents, isLoading, error } = useAgents({ databases: !agentId });
  const shared = useSharedAgents({ databases: !agentId });

  if (agentId) return <>{children}</>;

  // Only NL2SQL agents can be opened here; the rest belong to the agent UI.
  // Agents shared with the caller are offered too — they are usable here, so
  // leaving them out of the picker made them look unopenable.
  const choices = [...agents, ...shared.agents].filter(
    (agent) => agent.service_ref,
  );

  return (
    <>
      <PageHeader title="Select an agent" subtitle={purpose} />

      {error && (
        <Card className="mb-4">
          <EmptyState
            icon="warn"
            title="Could not load your agents"
            note={apiMessage(error)}
          />
        </Card>
      )}

      {isLoading && !choices.length ? (
        <AgentPickerSkeleton />
      ) : choices.length ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {choices.map((agent) => (
            <Card
              key={agent.agent_id}
              className="cursor-pointer transition-shadow hover:shadow-md"
            >
              <button
                type="button"
                className="w-full cursor-pointer text-left"
                onClick={() => router.push(agentRoute(route, agent.agent_id))}
              >
                <CardHeader
                  title={
                    <span className="flex items-center gap-2">
                      <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-indigo-50 text-indigo-600">
                        <Icon name="db" />
                      </span>
                      <span className="min-w-0">
                        <span className="block truncate text-sm font-semibold text-slate-900">
                          {agent.name}
                        </span>
                        <span className="block truncate text-xs font-normal text-slate-400">
                          {agent.dbs.length} database
                          {agent.dbs.length === 1 ? "" : "s"} connected
                        </span>
                      </span>
                    </span>
                  }
                  action={
                    <span className="flex items-center gap-1.5">
                      {agent.role && agent.role !== "owner" && (
                        <Chip tone="purple" size="sm">
                          {agent.role}
                        </Chip>
                      )}
                      <Chip tone={agent.active ? "green" : "slate"} size="sm">
                        {agent.active ? "Active" : "Paused"}
                      </Chip>
                    </span>
                  }
                />
                <CardBody className="text-sm text-slate-500">
                  {agent.role && agent.role !== "owner"
                    ? `Shared by ${agent.owner}`
                    : "Open this agent"}
                </CardBody>
              </button>
            </Card>
          ))}
        </div>
      ) : (
        <Card>
          <EmptyState
            title="No database agents yet"
            note="Create one from Home — connect a database and the agent is built for you."
          />
        </Card>
      )}
    </>
  );
}
