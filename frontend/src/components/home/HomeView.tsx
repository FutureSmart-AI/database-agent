"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import DemoAllowanceNote from "@/components/demo/DemoAllowanceNote";
import Icon from "@/components/Icon";
import { Card } from "@/components/ui/Card";
import Chip from "@/components/ui/Chip";
import EmptyState from "@/components/ui/EmptyState";
import PageHeader from "@/components/ui/PageHeader";
import SearchInput from "@/components/ui/SearchInput";
import { AgentGridSkeleton } from "@/components/ui/Skeletons";
import TabNav from "@/components/ui/TabNav";
import { usageTotals } from "@/data/agents";
import { useDemoAllowance } from "@/data/demo";
import { useAgentMutations } from "@/data/mutations";
import type { Agent } from "@/data/types";
import { useUsageByAgent } from "@/data/usage";
import { useAgents, useSharedAgents } from "@/data/useAgents";
import { apiMessage } from "@/lib/apiError";
import { copyText } from "@/lib/clipboard";
import { AGENT_CARD_HEIGHT, AGENT_GRID } from "@/lib/constants";
import { NL2SQL_FONT_CLASS } from "@/lib/fonts";
import { nfmt } from "@/lib/format";
import { agentRoute, ROUTES } from "@/lib/routes";
import { useToast } from "@/platform/components/ToastContext";
import { Button, Modal, Select } from "@/platform/components/ui";

import AgentCard from "./AgentCard";
import NewAgentWizard from "./NewAgentWizard";

type HomeTab = "mine" | "shared";

/**
 * Home — every NL2SQL agent in the workspace, plus the workspace-wide usage and
 * credentials entry points.
 */
export default function HomeView() {
  const router = useRouter();
  const { toast } = useToast();

  const [tab, setTab] = useState<HomeTab>("mine");
  // Opened by every "New agent" entry point. The wizard adds to the workspace and
  // `useAgents` re-reads it, so the new card appears without a reload.
  const [wizardOpen, setWizardOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [owner, setOwner] = useState("");
  const [pendingDelete, setPendingDelete] = useState<Agent | null>(null);
  /** Why the last delete failed, kept in the dialog so it cannot be missed. */
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const { remove: removeAgent } = useAgentMutations(pendingDelete ?? undefined);

  // Home is the one view that shows every agent's databases — its cards count
  // them and its search matches on database name — so it asks for them.
  const {
    agents: allAgents,
    isLoading,
    error,
  } = useAgents({
    databases: true,
  });
  const { agents: sharedAgents } = useSharedAgents({ databases: true });
  const usage = useUsageByAgent();
  // The registry has no usage; it is a separate call, merged in here.
  const agents = allAgents.map((agent) => ({
    ...agent,
    usage: usage.data?.[agent.agent_id] ?? agent.usage,
  }));
  const totals = usageTotals(agents);

  const needle = query.trim().toLowerCase();

  // Home lists the NL2SQL agents: an agent without that service belongs to the
  // main agent UI, not to this product. The shared example agent is kept by its
  // `demo` flag alone — it is a viewer row owned by someone else, and letting
  // every non-owned row through would leak genuinely shared agents in here.
  const mine = useMemo(
    () =>
      agents
        .filter(
          (agent) =>
            agent.service_ref &&
            (agent.demo || !agent.role || agent.role === "owner"),
        )
        .filter(
          (agent) =>
            !needle ||
            agent.name.toLowerCase().includes(needle) ||
            agent.dbs.some((db) => db.db_name.toLowerCase().includes(needle)),
        ),
    [agents, needle],
  );

  // Shared agents come from their own endpoint — they are not in the
  // owner-scoped list this page's "My agents" tab reads. They stay whole
  // `Agent`s: stripping them to a display-only shape is what left the shared
  // cards unopenable and without the databases they plainly have.
  const shared = useMemo(
    () => sharedAgents.filter((agent) => agent.service_ref),
    [sharedAgents],
  );

  const sharedMatches = useMemo(
    () =>
      shared.filter(
        (agent) =>
          (!needle ||
            agent.name.toLowerCase().includes(needle) ||
            agent.owner.toLowerCase().includes(needle) ||
            agent.dbs.some((db) =>
              db.db_name.toLowerCase().includes(needle),
            )) &&
          (!owner || agent.owner === owner),
      ),
    [shared, needle, owner],
  );

  const owners = useMemo(
    () => [...new Set(shared.map((agent) => agent.owner))],
    [shared],
  );
  const visibleOwners = useMemo(
    () => [...new Set(sharedMatches.map((agent) => agent.owner))],
    [sharedMatches],
  );

  // The shared sample-data agents, newest first: the quickest way to see the
  // product work, before connecting anything.
  const samples = useMemo(
    () =>
      agents
        .filter((agent) => agent.demo && agent.service_ref)
        .sort((a, b) => b.created - a.created),
    [agents],
  );
  const demoAllowance = useDemoAllowance(samples.length > 0);

  const shownCount = tab === "mine" ? mine.length : sharedMatches.length;
  const totalCount =
    tab === "mine"
      ? agents.filter((agent) => agent.service_ref).length
      : shared.length;

  const openAgent = (agent: Agent) =>
    router.push(agentRoute(ROUTES.conversations, agent.agent_id));

  const confirmDelete = async () => {
    if (!pendingDelete) return;
    setDeleteError(null);
    try {
      await removeAgent.mutateAsync(pendingDelete);
      toast.success(`${pendingDelete.name} deleted.`);
      setPendingDelete(null);
    } catch (error) {
      // The dialog stays open with the reason: a card that quietly refuses to
      // disappear reads as the list being stale.
      setDeleteError(apiMessage(error));
    }
  };

  const copyId = async (id: string, name: string) => {
    const copied = await copyText(id);
    toast[copied ? "success" : "error"](
      copied ? `Agent ID for ${name} copied.` : "Could not copy the agent ID.",
    );
  };

  // First card on the board, so the way to add an agent sits in the same place
  // however many agents the workspace already has — the loading skeleton
  // renders it too, so the one control that needs no data stays usable.
  const newAgentTile = (
    <button
      className={`group relative flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed border-indigo-200 bg-indigo-50/50 text-center transition-all duration-200 hover:border-indigo-400 hover:bg-indigo-50 hover:shadow-md ${AGENT_CARD_HEIGHT}`}
      onClick={() => setWizardOpen(true)}
      type="button"
      title="Create a new database agent"
    >
      <span className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-white text-indigo-600 shadow-sm ring-1 ring-indigo-100 transition-colors group-hover:scale-110 group-hover:text-indigo-700">
        <Icon name="plus" className="h-7 w-7" />
      </span>
      <span className="text-lg font-bold text-slate-900 group-hover:text-indigo-700">
        New database agent
      </span>
      <span className="mt-2 max-w-50 text-xs font-medium text-slate-500">
        Connect a database and we build the agent for you
      </span>
    </button>
  );

  return (
    <>
      {wizardOpen && <NewAgentWizard onClose={() => setWizardOpen(false)} />}

      <Modal
        open={Boolean(pendingDelete)}
        variant="danger"
        maxWidth="md"
        title={`Delete ${pendingDelete?.name ?? ""}?`}
        confirmText="Delete agent"
        confirmLoading={removeAgent.isPending}
        onConfirm={confirmDelete}
        onCancel={() => {
          setPendingDelete(null);
          setDeleteError(null);
        }}
      >
        {/* The shared Modal portals to `document.body`, outside the shell's
            subtree, so the confirmation re-enters the product's scope. */}
        <div className={`n2s-scope ${NL2SQL_FONT_CLASS}`}>
          <p className="text-sm text-slate-600">
            {(pendingDelete?.service_count ?? 0) > 1
              ? "Its databases, descriptions and few-shot examples go with it, and this agent stops answering questions about your data. The agent keeps its other services — only Database Agent is removed."
              : "Its databases, descriptions, examples and conversations go with it, and any share link or API key stops working."}{" "}
            The databases themselves are untouched.
          </p>
          {deleteError && (
            <p className="mt-3 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-900">
              {deleteError}
            </p>
          )}
        </div>
      </Modal>

      <PageHeader
        title="Your database agents"
        subtitle="Each agent answers questions about the databases you connect to it. Connect a database and the agent is built for you — nothing else to configure."
        action={
          <Button
            startIcon={<Icon name="plus" className="size-4" />}
            onClick={() => setWizardOpen(true)}
          >
            New agent
          </Button>
        }
      />

      {samples.length > 0 && (
        <section
          aria-labelledby="try-sample-data"
          className="mb-5 rounded-2xl border border-indigo-100 bg-linear-to-r from-indigo-50 to-white p-5 shadow-sm"
        >
          <div className="flex flex-wrap items-start gap-4">
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-white text-indigo-600 shadow-sm ring-1 ring-indigo-100">
              <Icon name="spark" className="h-6 w-6" />
            </div>
            <div className="min-w-60 flex-1">
              <h2
                id="try-sample-data"
                className="m-0 text-lg font-bold text-slate-900"
              >
                Try with sample data
              </h2>
              <p className="m-0 mt-1 max-w-[70ch] text-sm text-slate-600">
                Ask questions about a ready-made database — no API key or
                database of your own needed. The agent writes the SQL, runs it
                read-only, and shows you the rows, a chart and follow-up
                questions.
              </p>
              <div className="mt-2">
                <DemoAllowanceNote
                  allowance={demoAllowance.data}
                  variant="inline"
                />
              </div>
            </div>
          </div>
          <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {samples.map((agent) => (
              <button
                key={agent.agent_id}
                type="button"
                onClick={() => openAgent(agent)}
                className="group flex cursor-pointer flex-col gap-1 rounded-xl border border-black/5 bg-white p-4 text-left shadow-sm transition-all duration-200 hover:border-indigo-300 hover:shadow-md"
              >
                <span className="font-semibold text-slate-900 group-hover:text-indigo-700">
                  {agent.name}
                </span>
                <span className="text-xs text-slate-500">
                  {agent.dbs.length > 0
                    ? agent.dbs
                        .map((db) =>
                          db.table_count
                            ? `${db.db_name} · ${db.table_count} tables`
                            : db.db_name,
                        )
                        .join(", ")
                    : "Sample database"}
                </span>
                <span className="mt-2 inline-flex items-center gap-1 text-sm font-semibold text-indigo-600">
                  Ask a question
                  <Icon name="send" className="size-3.5" />
                </span>
              </button>
            ))}
          </div>
        </section>
      )}

      <div className="mb-5 grid grid-cols-1 gap-4 sm:grid-cols-2">
        <button
          type="button"
          onClick={() => router.push(ROUTES.usage)}
          className="group relative flex h-full cursor-pointer gap-4 overflow-hidden rounded-2xl border border-black/5 bg-white p-4 text-left shadow-sm transition-all duration-200 hover:border-indigo-200 hover:shadow-md"
        >
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-orange-50 text-orange-600 transition-colors group-hover:bg-orange-100">
            <Icon name="activity" className="h-6 w-6" />
          </div>
          <div className="flex w-full flex-col">
            <div className="flex w-full items-center justify-between">
              <h3 className="font-semibold text-slate-900 transition-colors group-hover:text-indigo-700">
                Usage &amp; Limits
              </h3>
              <span className="inline-flex items-center rounded-full bg-orange-50 px-2 py-0.5 text-[10px] font-medium text-orange-700 ring-1 ring-inset ring-orange-600/20">
                Last 30 Days
              </span>
            </div>
            <p className="mb-2 text-sm text-slate-500">
              View token usage across your agents
            </p>

            <div className="mt-auto flex w-full flex-row flex-wrap items-center gap-6">
              {(
                [
                  ["Total Tokens", totals.input_tokens + totals.output_tokens],
                  ["Input Tokens", totals.input_tokens],
                  ["Output Tokens", totals.output_tokens],
                ] as const
              ).map(([label, value]) => (
                <div
                  key={label}
                  className="group/stat flex items-center gap-2 transition-colors"
                >
                  <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 transition-colors group-hover/stat:text-indigo-500">
                    {label}
                  </span>
                  <span className="text-sm font-bold text-slate-700 transition-colors group-hover/stat:text-indigo-700">
                    {nfmt(value)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </button>

        {/*
         * A link to the credentials screen, not a dialog: that screen is where
         * the design keeps the keys — its own counts, its own table, its own
         * back link — and adding or editing one is a dialog on it. Popping the
         * form from here would skip the screen entirely.
         */}
        <Link
          href={ROUTES.credentials}
          className="group relative flex h-full cursor-pointer gap-4 overflow-hidden rounded-2xl border border-black/5 bg-white p-4 text-left shadow-sm transition-all duration-200 hover:border-indigo-200 hover:shadow-md"
        >
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-purple-50 text-purple-600 transition-colors group-hover:bg-purple-100">
            <Icon name="key" className="h-6 w-6" />
          </div>
          <div className="flex flex-col">
            <h3 className="font-semibold text-slate-900 transition-colors group-hover:text-indigo-700">
              Add Credentials
            </h3>
            <p className="mb-2 text-sm text-slate-500">
              Manage secure access keys for your agents &amp; services
            </p>
          </div>
        </Link>
      </div>

      <TabNav<HomeTab>
        className="mb-4"
        label="Agent ownership"
        activeTab={tab}
        onChange={setTab}
        tabs={[
          { key: "mine", label: "My Agents" },
          { key: "shared", label: "Shared With Me" },
        ]}
      />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Chip>
          Showing {shownCount} of {totalCount}
        </Chip>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <SearchInput
            className="w-64"
            label="Search agents"
            placeholder="Search agents…"
            value={query}
            onChange={setQuery}
          />
          {tab === "shared" && (
            <Select
              aria-label="Filter by owner"
              className="min-w-48"
              placeholder="Select owner"
              value={owner}
              onChange={setOwner}
              options={owners.map((value) => ({ value, label: value }))}
            />
          )}
        </div>
      </div>

      {error && (
        <Card className="mb-4">
          <EmptyState
            icon="warn"
            title="Could not load your agents"
            note={apiMessage(error)}
          />
        </Card>
      )}

      {isLoading && !agents.length ? (
        <AgentGridSkeleton
          leading={tab === "mine" ? newAgentTile : undefined}
        />
      ) : tab === "mine" ? (
        <div className={AGENT_GRID}>
          {mine.length > 0 ? (
            <>
              {newAgentTile}
              {mine.map((agent) => (
                <AgentCard
                  key={agent.agent_id}
                  agent={agent}
                  onOpen={openAgent}
                  onDelete={agent.demo ? undefined : setPendingDelete}
                />
              ))}
            </>
          ) : (
            <Card className="col-span-full">
              <EmptyState
                title={`No agents match “${query}”`}
                note="Try a different name, or create an agent for this database."
                action={
                  <Button
                    startIcon={<Icon name="plus" className="size-4" />}
                    onClick={() => setWizardOpen(true)}
                  >
                    New agent
                  </Button>
                }
              />
            </Card>
          )}
        </div>
      ) : visibleOwners.length > 0 ? (
        <div className="space-y-6">
          {visibleOwners.map((ownerEmail) => {
            const theirs = sharedMatches.filter(
              (agent) => agent.owner === ownerEmail,
            );
            return (
              <div key={ownerEmail}>
                <div className="mb-3 flex items-center gap-2 text-xs font-semibold text-slate-600">
                  <Icon name="users" className="size-4 text-slate-400" />
                  {ownerEmail}
                  <span className="font-normal text-slate-400">
                    ({theirs.length} agent{theirs.length === 1 ? "" : "s"})
                  </span>
                </div>
                {/* The same card as "My Agents", so a shared agent opens the
                    way an owned one does — clicking it anywhere. It used to be
                    a lookalike whose only live control was a small ghost
                    button, which read as a card that simply did not work. */}
                <div className={AGENT_GRID}>
                  {theirs.map((agent) => (
                    <AgentCard
                      key={agent.agent_id}
                      agent={agent}
                      onOpen={openAgent}
                      onCopyId={(entry) => copyId(entry.agent_id, entry.name)}
                    />
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <Card>
          <EmptyState
            title={`No shared agents match${query ? ` “${query}”` : ""}`}
            note="Try a different name or owner, or clear the filter."
          />
        </Card>
      )}
    </>
  );
}
