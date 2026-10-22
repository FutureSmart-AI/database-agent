import { buildApiUrl } from "@/platform/utils";
import axios from "@/platform/utils/axios";

import { APIS } from "./api";
import type {
  Agent,
  AgentAppearance,
  AgentDatabase,
  AgentFeatures,
  AgentShare,
  NodeConfig,
  UsageTotals,
} from "./types";

/**
 * Agent reads and writes, against the live API.
 *
 * The documented NL2SQL API owns the complete agent lifecycle. Its `agent_id`
 * is used directly for agent configuration, databases, sessions and questions.
 */

/**
 * `config.agent_params`, exactly as the NL2SQL service defines it
 * (`AgentParamsRequest` in its OpenAPI contract). These are the only fields
 * `PATCH …/config/params` accepts, so they are the only ones Settings sends.
 */
export interface Nl2sqlAgentParams {
  agent_name?: string;
  system_prompt?: string;
  service_description?: string;
  greet_message?: string;
  debug_info?: boolean;
  /** The executed SQL under an answer. */
  show_sql_query?: boolean | null;
  /** The rows the SQL read. */
  show_db_result?: boolean | null;
  /** Charts — `chart_output` in the chat registry. */
  graph_output?: boolean;
  allowed_graphs?: string[];
  follow_up?: boolean;
  voice_input_enabled?: boolean;
  voice_output_enabled?: boolean;
  suggested_questions?: string[];
  max_query_execution_time?: number;
  enable_query_caching?: boolean;
  /** Let the embedded widget be used without signing in. */
  is_public?: boolean;
  /** Domains the widget may be embedded on; empty means any domain. */
  allowed_domains?: string[];
  /** Let the full-screen share link be used without signing in. */
  fullscreen_is_public?: boolean;
  /** Domains the full-screen link may be opened from; empty means any. */
  fullscreen_allowed_domains?: string[];
}

/**
 * Field names the chat registry used for the same settings. Read, never written:
 * an agent configured before this product stopped routing through orchestration
 * still has its values under these keys.
 */
interface LegacyAgentParams {
  show_sources?: boolean;
  chart_output?: boolean;
  voice_input?: boolean;
  voice_output?: boolean;
  memory_enabled?: boolean;
  global_memory?: boolean;
  raw_response?: boolean;
  default_language?: string | null;
}

type RegistryAgentParams = Nl2sqlAgentParams & LegacyAgentParams;

/** An NL2SQL agent returned by `GET /nl2sql/api/v1/agents`. */
export interface RegistryAgent {
  agent_id: string;
  owner_id?: string;
  role?: string | null;
  /**
   * The shared example agent the service lists first in every caller's
   * `owned_agents`. One row serves every user, so its `owner_id` is not the
   * caller's and its `role` is `viewer`.
   */
  is_demo?: boolean;
  agent_name?: string;
  greet_message?: string | null;
  created_at?: string;
  updated_at?: string;
  last_modified?: string;
  config?: {
    agent_params?: RegistryAgentParams;
    nodes?: unknown[];
  };
}

interface RegistryAgentListResponse {
  data?: RegistryAgent[];
  agents?: RegistryAgent[];
  owned_agents?: RegistryAgent[];
  invited_agents?: RegistryAgent[];
  pagination?: {
    page?: number;
    pages?: number;
  };
}

const epoch = (value: string | null | undefined): number =>
  value ? Date.parse(value) : 0;

/** The NL2SQL service id for an agent, or `null` when it has no NL2SQL service. */
export function nl2sqlServiceId(agent: RegistryAgent): string | null {
  return agent.agent_id ?? null;
}

/**
 * The service's parameter names, read into the shape the views use.
 *
 * Each one falls back to the chat registry's name for it, so an agent that
 * predates the switch keeps showing what it has stored.
 */
export function toFeatures(params: RegistryAgentParams): AgentFeatures {
  return {
    show_sources: Boolean(
      params.show_sql_query ?? params.show_db_result ?? params.show_sources,
    ),
    follow_up: Boolean(params.follow_up),
    chart_output: Boolean(params.graph_output ?? params.chart_output),
    // No memory or raw-response flags exist on the NL2SQL service; these read
    // whatever an agent still has stored and are never written back.
    memory: Boolean(params.memory_enabled),
    global_memory: Boolean(params.global_memory),
    raw_response: Boolean(params.raw_response),
    voice_input: Boolean(params.voice_input_enabled ?? params.voice_input),
    voice_output: Boolean(params.voice_output_enabled ?? params.voice_output),
  };
}

/**
 * How the agent is shared, as the service's parameters describe it.
 *
 * All four fields are real `AgentParamsRequest` members and are written back by
 * the Share screen through `PATCH …/config/params`. They are **absent from the
 * agent row** returned by `GET /agents` and appear only under
 * `GET …/config?fields=agent_params`, so a caller that wants the stored state
 * (rather than "off, no domains") has to read the config.
 */
export function toShare(params: RegistryAgentParams): AgentShare {
  return {
    widget: Boolean(params.is_public),
    fullpage: Boolean(params.fullscreen_is_public),
    domains: params.allowed_domains ?? [],
    fullscreenDomains: params.fullscreen_allowed_domains ?? [],
    // Keys live behind the API-key endpoints, not the agent params.
    keys: [],
  };
}

/**
 * Appearance is only partly a registry field. The greeting and "show sources"
 * are stored on the agent; brand colour, launcher icon and chat avatar live in
 * the NL2SQL widget settings (`./widgetSettings.ts`), which the Share view
 * layers over these values and saves separately. What is returned here is the
 * starting point for an agent that has no widget settings stored yet.
 */
function toAppearance(
  params: RegistryAgentParams,
  name: string,
): AgentAppearance {
  return {
    heading: name,
    sub: "Query your database using natural language",
    greet:
      params.greet_message ||
      "Ask a question about your data in plain English.",
    color: "#4f46e5",
    show_sources: Boolean(params.show_sql_query ?? params.show_sources),
    icon: 0,
    avatar: 0,
  };
}

export function toAgent(row: RegistryAgent): Agent {
  const params: RegistryAgentParams = row.config?.agent_params ?? row;
  const name =
    params.agent_name?.trim() || row.agent_name?.trim() || row.agent_id;
  const service = { service_id: row.agent_id, status: "enabled" };

  return {
    agent_id: row.agent_id,
    owner: row.owner_id ?? "",
    service_ref: service?.service_id ?? null,
    service_count: 1,
    name,
    active: true,
    created: epoch(row.created_at),
    last_used: epoch(row.last_modified ?? row.updated_at),
    role: row.role ?? null,
    demo: row.is_demo === true,
    // Usage comes from the usage API (see ./usage.ts) — an agent row has none.
    usage: { requests: 0, input_tokens: 0, output_tokens: 0 },
    feats: toFeatures(params),
    suggested_questions: params.suggested_questions ?? [],
    default_language: params.default_language ?? null,
    appearance: toAppearance(params, name),
    // An agent row carries none of the four share fields — they come back only
    // from `GET …/config?fields=agent_params`, so Share reads them from there
    // (`toShare`) and this is a starting point, not the stored state.
    share: toShare(params),
    // Filled per agent by ./databases.ts — the registry does not carry them.
    dbs: [],
  };
}

/**
 * Every page of `GET /nl2sql/api/v1/agents`.
 *
 * One response carries both lists: `owned_agents` and the agents shared with
 * the caller in `invited_agents`, each row carrying its `role`.
 */
async function fetchAgentPages(
  ownerId: string,
): Promise<RegistryAgentListResponse[]> {
  const response = await axios.get<RegistryAgentListResponse>(
    APIS.NL2SQL_AGENTS,
    {
      params: { owner_id: ownerId },
    },
  );
  const responses = [response];
  const pages = response.data.pagination?.pages ?? 1;

  if (pages > 1) {
    responses.push(
      ...(await Promise.all(
        Array.from({ length: pages - 1 }, (_, index) =>
          axios.get<RegistryAgentListResponse>(APIS.NL2SQL_AGENTS, {
            params: { owner_id: ownerId, page: index + 2 },
          }),
        ),
      )),
    );
  }

  return responses.map((entry) => entry.data);
}

/** One card per agent id, in the order the service listed them. */
function uniqueAgents(rows: RegistryAgent[]): Agent[] {
  const byId = new Map<string, RegistryAgent>();
  for (const row of rows)
    if (!byId.has(row.agent_id)) byId.set(row.agent_id, row);
  return [...byId.values()].map(toAgent);
}

/** `GET /nl2sql/api/v1/agents` — the agents the caller owns. */
export async function fetchAgents(ownerId: string): Promise<Agent[]> {
  const pages = await fetchAgentPages(ownerId);
  return uniqueAgents(
    pages.flatMap(
      (page) => page.owned_agents ?? page.agents ?? page.data ?? [],
    ),
  );
}

/** `GET /nl2sql/api/v1/agents/{agent_id}` — one NL2SQL agent. */
export async function fetchAgent(agentId: string): Promise<Agent> {
  const url = buildApiUrl(APIS.NL2SQL_AGENT, { service_id: agentId });
  const response = await axios.get<{ data?: RegistryAgent } & RegistryAgent>(
    url,
  );
  return toAgent(response.data.data ?? response.data);
}

/**
 * `GET /nl2sql/api/v1/agents/{agent_id}/config?fields=agent_params` — the
 * settings the service holds for an agent.
 *
 * The configuration path, not the agent row: the service owns these parameters,
 * so Settings loads them from where they are written rather than from whatever
 * a list response happened to carry.
 */
export async function fetchAgentParams(
  serviceId: string,
): Promise<Nl2sqlAgentParams> {
  const url = buildApiUrl(APIS.NL2SQL_CONFIG, { service_id: serviceId });
  const response = await axios.get<{
    config?: { agent_params?: Nl2sqlAgentParams };
    agent_params?: Nl2sqlAgentParams;
  }>(url, { params: { fields: "agent_params" } });
  return response.data.config?.agent_params ?? response.data.agent_params ?? {};
}

/**
 * `PATCH /nl2sql/api/v1/agents/{agent_id}/config/params` — answer settings.
 *
 * Only the fields in `Nl2sqlAgentParams` are accepted, and callers send only the
 * ones they changed (see `changedParams`).
 */
export async function updateAgentParams(
  agentId: string,
  params: Partial<Nl2sqlAgentParams>,
): Promise<void> {
  const url = buildApiUrl(APIS.NL2SQL_PARAMS, { service_id: agentId });
  await axios.patch(url, params);
}

/** Same value? Arrays compare by contents, everything else by identity. */
function same(a: unknown, b: unknown): boolean {
  if (Array.isArray(a) || Array.isArray(b)) {
    return JSON.stringify(a ?? []) === JSON.stringify(b ?? []);
  }
  return a === b;
}

/** The subset of `next` that differs from what the service already holds. */
export function changedParams(
  loaded: Nl2sqlAgentParams | undefined,
  next: Partial<Nl2sqlAgentParams>,
): Partial<Nl2sqlAgentParams> {
  const patch: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(next)) {
    if (value === undefined) continue;
    if (!same(value, (loaded ?? {})[key as keyof Nl2sqlAgentParams])) {
      patch[key] = value;
    }
  }
  return patch as Partial<Nl2sqlAgentParams>;
}

/**
 * `POST /nl2sql/api/v1/agents` — provisions the NL2SQL service itself. Its
 * `agent_id` is the `service_id` every `/nl2sql/api/v1/agents/…` route is keyed
 * by; it is not the chat id.
 */
async function createNl2sqlService(input: {
  ownerId: string;
  name: string;
}): Promise<string> {
  const response = await axios.post<{ agent_id?: string; service_id?: string }>(
    APIS.NL2SQL_AGENTS,
    {
      owner_id: input.ownerId,
      agent_name: input.name,
      system_prompt: "",
      greet_message: "Ask a question about your data in plain English.",
    },
  );
  const serviceId = response.data.service_id ?? response.data.agent_id;
  if (!serviceId)
    throw new Error("The Database Agent service did not return an id.");
  return serviceId;
}

/**
/**
 * Provisions one NL2SQL agent. There is no chat-registry companion record: the
 * ID returned here is used by every screen in this application.
 */
export async function createNl2sqlAgent(input: {
  ownerId: string;
  name: string;
}): Promise<{ agent_id: string; service_id: string }> {
  const agentId = await createNl2sqlService(input);
  return { agent_id: agentId, service_id: agentId };
}

export interface RdsCredentials {
  db_host: string;
  db_engine: string;
  db_user: string;
  db_password: string;
  db_port?: number;
}

/** One database the RDS host reported. `table_count` is absent on older builds. */
export interface RdsDatabaseRow {
  db_name: string;
  table_count: number | null;
}

/**
 * `POST …/databases/rds/list` — databases visible on an RDS host, with the table
 * count the service reports for each.
 *
 * The service answers `databases: [{ db_name, table_count }]`, so the names are
 * read out of the rows rather than assuming a list of strings (which rendered
 * every database as "[object Object]"). A plain string row is still accepted, in
 * which case there is no count to show.
 */
export async function listRdsDatabaseRows(
  credentials: RdsCredentials,
): Promise<RdsDatabaseRow[]> {
  type Row =
    string | { db_name?: string; name?: string; table_count?: number | null };
  const response = await axios.post<{ data?: Row[]; databases?: Row[] }>(
    APIS.RDS_LIST,
    credentials,
  );
  const rows = response.data.databases ?? response.data.data ?? [];
  return rows
    .map((row) =>
      typeof row === "string"
        ? { db_name: row, table_count: null }
        : {
            db_name: row.db_name ?? row.name ?? "",
            table_count: row.table_count ?? null,
          },
    )
    .filter((row) => Boolean(row.db_name));
}

/** Just the names — what the new-agent wizard's picker needs. */
export async function listRdsDatabases(
  credentials: RdsCredentials,
): Promise<string[]> {
  const rows = await listRdsDatabaseRows(credentials);
  return rows.map((row) => row.db_name);
}

/**
 * `DELETE /nl2sql/api/v1/agents/{agent_id}` — removes the NL2SQL agent.
 */
export async function deleteNl2sqlAgent(agent: {
  agent_id: string;
  service_ref: string | null;
  service_count: number;
}): Promise<void> {
  const url = buildApiUrl(APIS.NL2SQL_AGENT, { service_id: agent.agent_id });
  await axios.delete(url);
}

/**
 * Labels and hints for the workflow nodes; the API returns only `node_name`.
 *
 * Keyed by the names the deployed service actually returns (`router`, `sql_gen`,
 * `db_router`, `select_table`, `chart_agent`, `final_answer_node`). Anything not
 * listed keeps its own name — readably cased — and no hint, rather than being
 * described as a step nobody has confirmed exists.
 */
const NODE_META: Record<string, { label: string; hint: string }> = {
  router: {
    label: "Understand the question",
    hint: "Rewrites the question into something answerable, using the conversation so far.",
  },
  db_router: {
    label: "Choose the database",
    hint: "Reads each database's description to decide where the question belongs.",
  },
  select_table: {
    label: "Pick tables and examples",
    hint: "Narrows the schema to the tables the question needs, plus the closest few-shot examples.",
  },
  sql_gen: {
    label: "Write the SQL",
    hint: "Writes the query itself — the step worth the strongest model.",
  },
  final_answer_node: {
    label: "Write the answer",
    hint: "Turns the rows into the prose answer people read.",
  },
  chart_agent: {
    label: "Build the chart",
    hint: "Decides whether a chart helps, and which one.",
  },
};

/** `final_answer_node` → "Final answer node", for a node with no entry above. */
const humanise = (nodeName: string) =>
  nodeName
    .replace(/_/g, " ")
    .replace(/^./, (character) => character.toUpperCase());

interface WireNode {
  node_name: string;
  provider: string;
  model: string;
  temperature: number;
  max_tokens?: number;
  prompt?: string;
  is_default: boolean;
}

/** `GET /nl2sql/api/v1/agents/{service_id}/config` — the workflow nodes. */
export async function fetchNodes(serviceId: string): Promise<NodeConfig[]> {
  const url = buildApiUrl(APIS.NL2SQL_CONFIG, { service_id: serviceId });
  const response = await axios.get<{ config: { nodes: WireNode[] } }>(url);

  return (response.data.config?.nodes ?? []).map((node) => ({
    node_name: node.node_name,
    label: NODE_META[node.node_name]?.label ?? humanise(node.node_name),
    hint: NODE_META[node.node_name]?.hint ?? "",
    provider: node.provider,
    model: node.model,
    temperature: node.temperature ?? 0,
    max_tokens: node.max_tokens ?? 1000,
    prompt: node.prompt ?? "",
    is_default: node.is_default,
  }));
}

/**
 * `POST /nl2sql/api/v1/agents/{service_id}/config/nodes` — saves the workflow
 * node configuration.
 *
 * POST, not PUT: the route only implements the POST upsert, so a PUT left the
 * configuration unchanged with no error to show for it. `owner_id` is the
 * service id, which is what the deployed endpoint expects (the same call the
 * main dashboard's node editor makes).
 */
export async function saveNodes(
  serviceId: string,
  nodes: NodeConfig[],
): Promise<{ message?: string }> {
  const url = buildApiUrl(APIS.NL2SQL_NODES, { service_id: serviceId });
  const response = await axios.post<{ message?: string }>(url, {
    owner_id: serviceId,
    configs: nodes.map((node) => ({
      node_name: node.node_name,
      provider: node.provider,
      model: node.model,
      temperature: node.temperature,
      max_tokens: node.max_tokens,
      prompt: node.prompt,
    })),
  });
  return response.data ?? {};
}

/**
 * `DELETE …/config/nodes/{node_name}` — puts one node back on the platform
 * default, server-side. Clearing the form only hid a saved override.
 */
export async function resetNode(
  serviceId: string,
  nodeName: string,
): Promise<{ message?: string }> {
  const url = buildApiUrl(APIS.NL2SQL_NODE, {
    service_id: serviceId,
    node_name: nodeName,
  });
  const response = await axios.delete<{ message?: string }>(url);
  return response.data ?? {};
}

/**
 * `GET /nl2sql/api/v1/agents` — the agents shared with the caller.
 *
 * The same call as `fetchAgents`, read from its other list. Never the chat
 * registry's share route, whose ids are incompatible with this product.
 */
export async function fetchSharedAgents(ownerId: string): Promise<Agent[]> {
  const pages = await fetchAgentPages(ownerId);
  return uniqueAgents(pages.flatMap((page) => page.invited_agents ?? []));
}

/** Workspace token totals, summed over the agents the caller loaded usage for. */
export function usageTotals(agents: Agent[]): UsageTotals {
  return agents.reduce<UsageTotals>(
    (total, agent) => ({
      requests: total.requests + agent.usage.requests,
      input_tokens: total.input_tokens + agent.usage.input_tokens,
      output_tokens: total.output_tokens + agent.usage.output_tokens,
    }),
    { requests: 0, input_tokens: 0, output_tokens: 0 },
  );
}

/** Tables an agent may read, summed across its databases. */
export function includedTableCount(dbs: AgentDatabase[]): number {
  return dbs.reduce((total, db) => total + db.included_table_count, 0);
}
