/**
 * Domain types for the standalone NL2SQL product.
 *
 * Field names follow the backend contract already implemented in the root app's
 * `src/services/nl2sql-databases.ts` and `src/services/nl2sql.ts` (`db_id`,
 * `db_engine`, `description_source`, …) so the fixture-backed data layer in
 * `./agents.ts` can be swapped for real API calls without touching the views.
 */

export type DbEngine = "mysql" | "postgresql" | (string & {});

/** Origin of a database's description; `null` until one exists. */
export type DescriptionSource = "manual" | "auto" | null;

/** State of a database's description, as the service reports it. */
export type DescriptionStatus = "set" | "generating" | "failed" | "none";

/** Last connection result, as the service reports it. */
export type ConnectionStatus = "untested" | "connected" | "error";

export interface AgentDatabase {
  db_id: string;
  db_name: string;
  db_engine: DbEngine;
  db_host: string;
  db_port: number;
  db_user: string;
  /** `is_active` on the wire: may the agent route questions here. */
  active: boolean;
  /** Derived from `status` — only "connected" counts as reachable. */
  reachable: boolean;
  /** Round trip of the last check this session, in ms; `null` until measured. */
  latency: number | null;
  description: string | null;
  description_status: DescriptionStatus;
  description_source: DescriptionSource;
  /** Epoch ms, parsed from the API's ISO string; `null` when there is none. */
  description_updated_at: number | null;
  /** `null` until the schema has been read. */
  table_count: number | null;
  /**
   * Tables the agent may read, from the database's visibility settings;
   * `null` when the service reports none (unknown, so never shown as 0).
   */
  included_table_count: number | null;
}

export interface AgentUsage {
  requests: number;
  input_tokens: number;
  output_tokens: number;
}

/**
 * What an answer is allowed to carry. Set per agent under Settings → Answers;
 * the chat surface reads these to decide which parts of a turn to render.
 */
export interface AgentFeatures {
  show_sources: boolean;
  follow_up: boolean;
  chart_output: boolean;
  /** `memory_enabled` on the wire. */
  memory: boolean;
  global_memory: boolean;
  /** Shows the raw API payload under each answer. */
  raw_response: boolean;
  /** Shows the mic in the composer. */
  voice_input: boolean;
  /** Shows a read-aloud button on each answer. */
  voice_output: boolean;
}

/** How the shared chat looks to the people who use it. */
export interface AgentAppearance {
  heading: string;
  sub: string;
  greet: string;
  /** Brand colour, used for the header, launcher and send button. */
  color: string;
  /** Whether viewers can open the SQL behind an answer. */
  show_sources: boolean;
  /** Index into the launcher icon presets. */
  icon: number;
  /** Index into the chat avatar presets. */
  avatar: number;
}

/** An API key issued for programmatic asking. Never returned in the clear. */
export interface ApiKey {
  id: string;
  masked: string;
  /**
   * The key itself, when the listing returns it — the NL2SQL service shows a
   * caller their own keys in full, which is what lets the view offer Copy and
   * a reveal toggle rather than only the masked form.
   */
  secret: string | null;
  /** Epoch ms the key was created. */
  created: number;
  /** False once revoked — the endpoint keeps returning revoked keys. */
  active: boolean;
}

/**
 * How an agent is exposed to other people.
 *
 * The two channels carry their own domain list on the service
 * (`allowed_domains` / `fullscreen_allowed_domains`), so they are kept apart
 * here too — a site allowed to embed the bubble is not necessarily one the
 * full-page link should open from.
 */
export interface AgentShare {
  /** Chat bubble embedded on a website. */
  widget: boolean;
  /** Full-page chat link. */
  fullpage: boolean;
  /** Domains allowed to load the widget; empty means anywhere. */
  domains: string[];
  /** Domains the full-page link may be opened from; empty means anywhere. */
  fullscreenDomains: string[];
  keys: ApiKey[];
}

/** Someone with access to the agent. */
export interface Person {
  email: string;
  role: "owner" | "editor" | "viewer";
  /** Human-formatted join date, as the artifact stores it. */
  since: string;
}

/** One workflow step's model configuration (`config.nodes`). */
export interface NodeConfig {
  node_name: string;
  /** Human label; the API returns only `node_name`. */
  label: string;
  provider: string;
  model: string;
  temperature: number;
  max_tokens: number;
  prompt: string;
  is_default: boolean;
  hint: string;
}

/** One NL2SQL agent: a question-answering front end over one or more databases. */
export interface Agent {
  /** Chat registry id — analytics, sessions and chat are keyed by this. */
  agent_id: string;
  /** The account that owns it (`owner_id`), which is an email. */
  owner: string;
  /**
   * NL2SQL service id (`NL2SQL_XXXXXXXX`). Every `/nl2sql/api/v1/agents/…`
   * route is keyed by this, **not** by `agent_id`: the service answers
   * "No agent found for service_id" when given the chat id.
   */
  service_ref: string | null;
  /** How many services the agent carries; deleting only ours if it has more. */
  service_count: number;
  name: string;
  active: boolean;
  /** Epoch ms. */
  created: number;
  /** Epoch ms of the last change. */
  last_used: number;
  /** The caller's role on this agent, when the registry reports one. */
  role: string | null;
  /**
   * The shared example agent (`is_demo` on the wire). Listed under My Agents
   * and chat works, but it is one row for every user: rename, settings, share
   * and delete belong to its real owner only.
   */
  demo: boolean;
  usage: AgentUsage;
  feats: AgentFeatures;
  /** Starter questions shown in the composer; `suggested_questions` on the wire. */
  suggested_questions: string[];
  /** Transcription language, `null` when it is auto-detected. */
  default_language: string | null;
  appearance: AgentAppearance;
  share: AgentShare;
  dbs: AgentDatabase[];
}

/** An agent owned by someone else and shared with the signed-in user. */
export interface SharedAgent {
  id: string;
  agent_id: string;
  name: string;
  owner: string;
  role: "Editor" | "Viewer" | (string & {});
  provider: string;
  model: string;
  service: string;
}

/** Workspace-wide token totals shown in Home → Usage & Limits. */
export interface UsageTotals {
  requests: number;
  input_tokens: number;
  output_tokens: number;
}
