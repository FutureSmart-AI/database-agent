"use client";

import { useRouter } from "next/navigation";

import Icon from "@/components/Icon";
import Chip from "@/components/ui/Chip";
import type { Agent } from "@/data/types";
import { AGENT_CARD_HEIGHT, BADGES_PER_CARD } from "@/lib/constants";
import { agentRoute, ROUTES } from "@/lib/routes";
import { Button } from "@/platform/components/ui";

interface AgentCardProps {
  agent: Agent;
  onOpen: (agent: Agent) => void;
  /**
   * Asks the workspace to confirm and delete this agent. Omitted for an agent
   * somebody else owns — a viewer or editor has no business deleting it, and
   * offering the action only to refuse it later is worse than not offering it.
   */
  onDelete?: (agent: Agent) => void;
  /** Copies the agent id, when the surface offers that. */
  onCopyId?: (agent: Agent) => void;
}

export default function AgentCard({
  agent,
  onOpen,
  onDelete,
  onCopyId,
}: AgentCardProps) {
  const router = useRouter();
  // The example agent is a viewer row too, but it is badged as an example
  // rather than by role, and offers neither owner actions nor the copy slot.
  const shared = Boolean(!agent.demo && agent.role && agent.role !== "owner");
  const offline = agent.dbs.filter((db) => !db.reachable).length;
  const undocumented = agent.dbs.filter((db) => !db.description).length;

  // Every card is the same height, so the badges are capped rather than
  // expandable: what does not fit becomes "+N more". The count under the name
  // says how many databases there are, and the agent's own pages list them all.
  const badges: Array<{ key: string; node: React.ReactNode }> = [
    ...(agent.demo
      ? [
          {
            key: "example",
            node: (
              <Chip tone="purple" size="sm" title="A shared example agent">
                Example
              </Chip>
            ),
          },
        ]
      : []),
    ...(shared
      ? [
          {
            key: "role",
            node: (
              <Chip tone="purple" size="sm">
                {agent.role}
              </Chip>
            ),
          },
        ]
      : []),
    {
      key: "status",
      node: (
        <Chip tone={agent.active ? "green" : "slate"} size="sm">
          <span
            className={`h-1.5 w-1.5 rounded-full ${
              agent.active ? "bg-emerald-500" : "bg-slate-400"
            }`}
          />
          {agent.active ? "Active" : "Paused"}
        </Chip>
      ),
    },
    ...(offline
      ? [
          {
            key: "offline",
            node: (
              <Chip tone="rose" size="sm">
                {offline} offline
              </Chip>
            ),
          },
        ]
      : []),
    ...(undocumented
      ? [
          {
            key: "undocumented",
            node: (
              <Chip tone="amber" size="sm">
                {undocumented} need{undocumented === 1 ? "s" : ""} description
              </Chip>
            ),
          },
        ]
      : []),
    ...agent.dbs.map((db) => ({
      key: `db-${db.db_id}`,
      node: (
        <Chip tone="blue" size="sm" title={db.db_name}>
          <span className="max-w-30 truncate font-mono">{db.db_name}</span>
          <span className="rounded-sm bg-white/60 px-1 font-semibold">
            {db.db_engine}
          </span>
        </Chip>
      ),
    })),
  ];
  const shown =
    badges.length > BADGES_PER_CARD
      ? badges.slice(0, BADGES_PER_CARD - 1)
      : badges;
  const hidden = badges.length - shown.length;

  const actions = (
    [
      {
        key: "analytics",
        icon: <Icon name="chart" className="h-4 w-4" />,
        label: `Analytics for ${agent.name}`,
        title: "Agent Analytics",
        run: () => router.push(agentRoute(ROUTES.analytics, agent.agent_id)),
      },
      // One example row serves every user, so its settings (rename included) and
      // sharing are its real owner's alone.
      !agent.demo && {
        key: "settings",
        icon: <Icon name="cog" className="h-4 w-4" />,
        label: `Settings for ${agent.name}`,
        title: "Settings",
        run: () => router.push(agentRoute(ROUTES.settings, agent.agent_id)),
      },
      // Sharing an agent is the owner's call, so a shared card offers the copy
      // action in that slot instead.
      agent.demo
        ? null
        : shared
          ? onCopyId && {
              key: "copy",
              icon: <Icon name="copy" className="h-4 w-4" />,
              label: `Copy the ID of ${agent.name}`,
              title: "Copy agent ID",
              run: () => onCopyId(agent),
            }
          : {
              key: "share",
              icon: <Icon name="share" className="h-4 w-4" />,
              label: `Share ${agent.name}`,
              title: "Share",
              run: () => router.push(agentRoute(ROUTES.share, agent.agent_id)),
            },
      onDelete &&
        !agent.demo && {
          key: "delete",
          icon: <Icon name="trash" className="h-4 w-4" />,
          label: `Delete ${agent.name}`,
          title: "Delete",
          run: () => onDelete(agent),
        },
    ].filter(Boolean) as Array<{
      key: string;
      icon: React.ReactNode;
      label: string;
      title: string;
      run: () => void;
    }>
  ).map((action, index) => (
    <span key={action.key} className="flex items-center">
      {index > 0 && <span className="mx-1 h-4 w-px bg-slate-200" />}
      <Button
        size="icon"
        variant="ghost"
        className="h-8 w-8 text-slate-500 hover:bg-indigo-50 hover:text-indigo-600"
        aria-label={action.label}
        title={action.title}
        onClick={(event) => {
          // The whole card opens the agent, so a row action must not bubble up
          // into it.
          event.stopPropagation();
          action.run();
        }}
        startIcon={action.icon}
      />
    </span>
  ));

  return (
    <div className="cursor-pointer">
      <div
        role="button"
        tabIndex={0}
        aria-label={`Open ${agent.name}`}
        onClick={() => onOpen(agent)}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            onOpen(agent);
          }
        }}
        className={`group relative flex flex-col overflow-hidden rounded-2xl border border-slate-200 bg-linear-to-br from-blue-50 to-white/80 shadow-sm transition-all duration-200 hover:-translate-y-1 hover:border-blue-200 hover:shadow-xl ${AGENT_CARD_HEIGHT}`}
      >
        <div className="flex grow flex-col items-center overflow-hidden p-5 text-center">
          <div className="relative mb-3 shrink-0">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl border border-blue-200 bg-blue-100 text-blue-600 shadow-inner">
              <Icon name="db" className="h-7 w-7" />
            </div>
          </div>

          {/* `shrink-0` on the name and the count: the card is a fixed height, so
              an agent with many databases would otherwise squeeze its own name
              out of existence. The badges below are what gets clipped. */}
          <h3 className="line-clamp-1 w-full shrink-0 text-lg font-bold text-slate-900 transition-colors group-hover:text-indigo-600">
            {agent.name}
          </h3>

          <div className="mt-2 flex shrink-0 items-center justify-center gap-1.5 text-xs font-medium text-slate-500">
            <Icon name="spark" className="h-3 w-3 text-indigo-500" />
            <span className="max-w-50 truncate">
              {agent.dbs.length} database
              {agent.dbs.length === 1 ? "" : "s"} connected
            </span>
          </div>

          <div className="mt-3 flex flex-wrap content-start justify-center gap-2 overflow-hidden">
            {shown.map((badge) => (
              <span key={badge.key} className="contents">
                {badge.node}
              </span>
            ))}
            {hidden > 0 && (
              <Chip tone="slate" size="sm">
                +{hidden} more
              </Chip>
            )}
          </div>
        </div>

        <div className="relative mt-auto flex h-14 items-center justify-center border-t border-slate-100 bg-white/50 px-4">
          <div className="flex items-center">{actions}</div>
        </div>
      </div>
    </div>
  );
}
