"use client";

import { useQueries, useQuery } from "@tanstack/react-query";
import { isAxiosError } from "axios";

import {
  fetchAgent,
  fetchAgentParams,
  fetchAgents,
  fetchSharedAgents,
} from "./agents";
import { fetchDatabases, fetchTables } from "./databases";
import { useOwnerId } from "./session";
import type { Agent } from "./types";

// Database lists are used for read-only card counts and search. Mutations
// explicitly invalidate these keys, so treating them as fresh between edits
// avoids reloading every connection whenever the dashboard regains focus.
const databaseListQueryOptions = {
  staleTime: 5 * 60 * 1000,
  refetchOnWindowFocus: false,
} as const;

/** Whether a list hook should also load every agent's databases. */
interface AgentListOptions {
  /**
   * Defaults to false: the databases are a call per agent, so a view that only
   * needs names and ids — the shell's agent count, Usage's labels — must not
   * pay a request per agent in the workspace to render one page. Views that
   * show a database count per agent (Home, the agent picker) opt in.
   */
  databases?: boolean;
}

/**
 * Attaches each NL2SQL agent's databases, which the registry row does not carry.
 *
 * One call per `service_id`, so the list a view renders is complete rather than
 * each view fetching databases for itself.
 */
function useDatabasesFor(
  agents: Agent[],
  enabled = true,
): {
  withDatabases: Agent[];
  isLoading: boolean;
} {
  const nl2sqlAgents = enabled
    ? agents.filter((agent) => agent.service_ref)
    : [];
  // A service can appear more than once while owned and shared registry data is
  // reconciled. `useQueries` must receive one entry per service, otherwise the
  // same endpoint is observed repeatedly for no additional data.
  const serviceIds = [
    ...new Set(nl2sqlAgents.map((agent) => agent.service_ref)),
  ];

  const databases = useQueries({
    queries: serviceIds.map((serviceId) => ({
      queryKey: ["databases", serviceId],
      queryFn: () => fetchDatabases(serviceId as string),
      enabled: Boolean(serviceId),
      ...databaseListQueryOptions,
    })),
  });

  const byService = new Map(
    serviceIds.map((serviceId, index) => [
      serviceId,
      databases[index]?.data ?? [],
    ]),
  );

  return {
    withDatabases: agents.map((agent) =>
      agent.service_ref
        ? { ...agent, dbs: byService.get(agent.service_ref) ?? [] }
        : agent,
    ),
    isLoading: databases.some((query) => query.isLoading),
  };
}

/**
 * The workspace's agents, live.
 *
 * The registry call returns the agents; each NL2SQL agent's databases are a
 * second call keyed by its `service_id`, and only for callers that ask for them
 * — see `AgentListOptions`. Everything stays disabled until the profile
 * resolves, since every request is scoped by `owner_id`.
 */
export function useAgents(options: AgentListOptions = {}): {
  agents: Agent[];
  isLoading: boolean;
  error: Error | null;
} {
  const ownerId = useOwnerId();

  const list = useQuery({
    queryKey: ["agents", ownerId],
    queryFn: () => fetchAgents(ownerId as string),
    enabled: Boolean(ownerId),
  });

  const { withDatabases, isLoading } = useDatabasesFor(
    list.data ?? [],
    options.databases ?? false,
  );

  return {
    agents: withDatabases,
    isLoading: list.isLoading || isLoading,
    error: (list.error as Error) ?? null,
  };
}

/**
 * Agents shared with the signed-in user.
 *
 * A separate call on purpose: the owner-scoped list only ever returns agents the
 * caller owns, so filtering it by role left "Shared with me" permanently empty.
 * Their databases are loaded the same way, so a shared agent can be opened and
 * asked questions rather than only listed.
 */
export function useSharedAgents(options: AgentListOptions = {}): {
  agents: Agent[];
  isLoading: boolean;
  error: Error | null;
} {
  const ownerId = useOwnerId();
  const query = useQuery({
    queryKey: ["shared-agents", ownerId],
    queryFn: () => fetchSharedAgents(ownerId as string),
    enabled: Boolean(ownerId),
  });

  const { withDatabases, isLoading } = useDatabasesFor(
    query.data ?? [],
    options.databases ?? false,
  );

  return {
    agents: withDatabases,
    isLoading: query.isLoading || isLoading,
    error: (query.error as Error) ?? null,
  };
}

/**
 * One agent by id, exactly — owned or shared.
 *
 * Both lists are searched: an agent someone shared is not in the owner-scoped
 * list, so opening one used to land on "No agent" no matter how it was reached.
 *
 * No fallback to the first agent: a view reached without `?agentId=` is asking
 * about an agent nobody picked, and showing one anyway made the whole shell —
 * topbar chip included — claim an agent was open. `AgentScope` asks which one
 * before these views render.
 *
 * An id neither list knows is read directly instead: the lists are cached for
 * minutes and never refetched on mount, so an agent created a moment ago — or
 * one reached by a link — otherwise resolved to nothing, and the shell dropped
 * its rail and agent chip on a page that plainly had an agent open.
 *
 * Only this agent's databases are fetched. The lists are read without theirs:
 * opening one agent used to cost a `/databases` call for every agent in the
 * workspace, since every agent-scoped page reads both lists through here.
 */
export function useAgent(agentId: string | undefined): {
  agent: Agent | undefined;
  isLoading: boolean;
  error: Error | null;
} {
  const owned = useAgents();
  const shared = useSharedAgents();

  const listed = agentId
    ? (owned.agents.find((entry) => entry.agent_id === agentId) ??
      shared.agents.find((entry) => entry.agent_id === agentId))
    : undefined;

  const direct = useQuery({
    queryKey: ["agent", agentId],
    // An id this account cannot see answers 403 or 404, which is an answer worth
    // caching: a query left in an error state holds no data, and every consumer
    // that mounts without data fetches again — so the three components reading
    // this hook on a page each re-asked for the same forbidden id.
    queryFn: async () => {
      try {
        return await fetchAgent(agentId as string);
      } catch (error) {
        const status = isAxiosError(error) ? error.response?.status : undefined;
        if (status === 403 || status === 404) return null;
        throw error;
      }
    },
    retry: false,
    staleTime: 5 * 60 * 1000,
    // Asked for as soon as the id is known, rather than after both lists settle.
    // Waiting made every agent-scoped page — Share worst of all — sit blank
    // through a serial chain: workspace list page 1, then page 2, then this
    // agent, then its databases. One extra small GET for an agent that is also
    // in the list is a far better trade than seconds of empty page.
    enabled: Boolean(agentId),
  });

  // The registry row carries no databases, from either route — so the one agent
  // being opened gets the attach step the lists no longer run for everyone.
  // Whichever call answers first wins: the direct read usually beats the lists.
  // The single-agent route does not carry `is_demo` — only the list does — so
  // the example agent keeps its flag from the list row whichever call won.
  const found = direct.data
    ? { ...direct.data, demo: direct.data.demo || Boolean(listed?.demo) }
    : listed;
  const { withDatabases, isLoading: databasesLoading } = useDatabasesFor(
    found ? [found] : [],
  );
  const agent = withDatabases[0];

  return {
    agent,
    // Once the agent is in hand the page can render; the workspace lists are
    // only used for the shell's count and are allowed to arrive later.
    isLoading: agent
      ? databasesLoading
      : owned.isLoading || shared.isLoading || direct.isLoading,
    // A shared-list failure must not hide an agent the caller owns.
    error: (owned.error ?? (agent ? null : shared.error)) as Error | null,
  };
}

/**
 * One agent's `agent_params`, read from the service's configuration path
 * (`GET …/config?fields=agent_params`).
 *
 * Settings edits a draft of this rather than of whatever a list response
 * carried, so what the form shows is what the service holds — and a save can
 * send only the fields that actually changed.
 */
export function useAgentParams(serviceId: string | null | undefined) {
  return useQuery({
    queryKey: ["agent-params", serviceId],
    queryFn: () => fetchAgentParams(serviceId as string),
    enabled: Boolean(serviceId),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });
}

/** A database's tables, live. */
export function useTables(
  serviceId: string | null | undefined,
  dbId: string | undefined,
) {
  return useQuery({
    queryKey: ["tables", serviceId, dbId],
    queryFn: () => fetchTables(serviceId as string, dbId as string),
    enabled: Boolean(serviceId && dbId),
  });
}
