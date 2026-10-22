"use client";

import { parseDbOutput } from "@/platform/components/conversations/nl2sql/parseDbOutput";
import type { ChatStreamTransport } from "@/platform/hooks/useChatStream";
import { buildApiUrl } from "@/platform/utils";
import axios from "@/platform/utils/axios";

import { APIS } from "./api";

/**
 * Asking and reading a conversation through the NL2SQL service itself.
 *
 * This product no longer routes questions through the chat service: a question
 * goes to `POST /nl2sql/api/v1/agents/{service_id}/chat?stream=true` and the
 * thread is read back from that service's own session routes. Everything the
 * chat UI does with the answer — accumulating chunks, the SQL / rows / chart
 * panels, follow-up questions, raw view — is unchanged; only the wire shape
 * differs, and that difference lives here:
 *
 * - the answer streams on `data:` lines, the turn's metadata on a
 *   `full_metadata:` line (`chat_id`, `follow_up`, `debug_info`,
 *   `chart_output`), which the chat service sends as one `data:` event;
 * - the SQL, the tables and the rows arrive as `debug_info.sql_query`,
 *   `debug_info.selected_tables` and `debug_info.db_result`, where the chat
 *   service nests the same values under `data.nl2sql`.
 *
 * So the adapters below re-shape NL2SQL's payloads into the ones the shared
 * chat components already read, rather than teaching every component a second
 * shape.
 */

/** `debug_info` as the NL2SQL service returns it. */
interface Nl2sqlDebugInfo {
  query?: string;
  refined_query?: string;
  refine_query?: string;
  selected_db_id?: string;
  selected_db_name?: string;
  sql_query?: string;
  selected_tables?: string[];
  db_result?: unknown;
  db_output?: unknown;
  latency_ms?: number;
}

/** `chart_output` as the NL2SQL service returns it. */
interface Nl2sqlChartOutput {
  chart_suggestion?: string;
  chart_data?: { data?: unknown; metadata?: unknown };
  metadata?: unknown;
}

/** Blanks out bracketed groups, keeping every offset intact. */
function withoutBrackets(sql: string): string {
  let depth = 0;
  return [...sql]
    .map((char) => {
      if (char === "(") {
        depth += 1;
        return " ";
      }
      if (char === ")") {
        depth = Math.max(0, depth - 1);
        return " ";
      }
      return depth > 0 ? " " : char;
    })
    .join("");
}

/**
 * The tables a query read, taken off the query itself.
 *
 * `debug_info.selected_tables` is the field the block wants, and this service
 * does not send it — so without this the result card had no table chip and the
 * run trace had no "Read table" row, on every answer.
 *
 * Bracketed groups are blanked first: the `FROM` in `EXTRACT(MONTH FROM
 * created_at)` names a column, not a table. A schema-qualified name keeps only
 * its table, and an alias after the name is not one of the names.
 */
export function tablesFromSql(sql: string): string[] {
  const names = new Set<string>();
  const pattern =
    /\b(?:from|join)\s+"?([A-Za-z_][\w$]*)"?(?:\."?([\w$]+)"?)?/gi;
  const flat = withoutBrackets(sql);
  let match = pattern.exec(flat);
  while (match) {
    names.add(match[2] ?? match[1]);
    match = pattern.exec(flat);
  }
  return [...names];
}

/**
 * The header cells of the first markdown table in an answer.
 *
 * `db_output` carries no column names, and a `SELECT *` gives the parser
 * nothing to recover them from — every column comes back as `column_1`,
 * `column_2`. The answer the model wrote alongside those rows almost always
 * names them, so its own table header is the honest source. Used only when the
 * widths agree, since a header slid one column over is worse than a positional
 * one.
 */
export function headersFromMarkdown(text: string | undefined): string[] {
  if (!text) return [];
  const lines = text.split("\n");
  for (let i = 0; i < lines.length - 1; i += 1) {
    const header = lines[i];
    const rule = lines[i + 1];
    if (!header.includes("|")) continue;
    if (!/^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$/.test(rule)) continue;
    const cells = header
      .trim()
      .replace(/^\|/, "")
      .replace(/\|$/, "")
      .split("|")
      // A header cell is markdown: "**Count**" is the word Count in bold, and
      // carrying the asterisks through put "**COUNT**" on the column.
      .map((cell) => cell.replace(/[*_`]/g, "").trim());
    if (cells.length > 1 && cells.every(Boolean)) return cells;
  }
  return [];
}

/** True when the parser fell back to a position rather than a real name. */
const isPositionalName = (name: string, index: number): boolean =>
  name === `column_${index + 1}`;

/** True when any column of a stored result is still nameless. */
const hasPositionalColumn = (columns: Array<{ name: string }>): boolean =>
  columns.some((column, index) => isPositionalName(column.name, index));

/** The `data.nl2sql` block the SQL / result / chart panels read. */
function toNl2sqlBlock(
  debug: Nl2sqlDebugInfo | null | undefined,
  chart: Nl2sqlChartOutput | null | undefined,
  answer?: string,
): Record<string, unknown> | null {
  const block: Record<string, unknown> = {};
  if (debug?.sql_query) block.sql_query = debug.sql_query;
  const tables = debug?.selected_tables?.length
    ? debug.selected_tables
    : debug?.sql_query
      ? tablesFromSql(debug.sql_query)
      : [];
  if (tables.length) block.tables_used = tables;
  // A live turn carries `db_result`; a stored one keeps the same rows as
  // `db_output`, positionally and as a string — see `parseDbOutput`.
  const stored = debug?.db_result
    ? null
    : parseDbOutput(debug?.db_output, debug?.sql_query);
  /**
   * Nameless columns, named from the answer's own table.
   *
   * `db_output` carries no column names. The parser recovers what it can from
   * the query — `SELECT status, COUNT(*)` names the first column and leaves the
   * second as `column_2` — and the answer the model wrote almost always names
   * both. Recovery used to run only when *every* column was positional, so the
   * common half-recovered case kept its `COLUMN_2` header on screen after a
   * reload. Each positional column now takes the header in its own position,
   * and a column the parser did name is left alone.
   */
  if (stored && hasPositionalColumn(stored.columns)) {
    const headers = headersFromMarkdown(answer);
    if (headers.length === stored.columns.length) {
      const names = stored.columns.map((column, index) =>
        isPositionalName(column.name, index) ? headers[index] : column.name,
      );
      stored.columns = names.map((name) => ({ name }));
      stored.rows = stored.rows.map((row) =>
        Object.fromEntries(
          Object.values(row).map((value, index) => [names[index], value]),
        ),
      );
    }
  }
  if (debug?.db_result) block.db_result = debug.db_result;
  else if (stored) block.db_result = stored;
  if (debug?.selected_db_name) block.db_name = debug.selected_db_name;
  if (chart?.chart_suggestion) block.chart_suggestion = chart.chart_suggestion;
  if (chart?.chart_data) block.chart_data = chart.chart_data;
  return Object.keys(block).length ? block : null;
}

/**
 * `POST …/{service_id}/chat` takes a different body from the chat service:
 * no `agent_id` (it is in the path) and no chunk count. Rewriting the caller's
 * payload here keeps the shared chat components — which build the chat-service
 * payload — untouched.
 *
 * `debug_info`, `chart_output`, `follow_up` and `allowed_charts` are all
 * optional, and an explicit value in the body **overrides** the agent's saved
 * setting. Sending them from here is what made Settings → Answers look inert:
 * `debug_info: true` kept the sources block on with "Show sources" off,
 * `follow_up: true` kept follow-ups on, and `chart_output: false` meant charts
 * could never come back on. Omitted, the service resolves each one from the
 * agent's configuration, which keeps one source of truth and needs no refetch
 * after a save.
 *
 * A surface that must never expose SQL whatever the agent is configured to do —
 * the embedded widget, a public share link — is the one case that should still
 * send `debug_info: false` explicitly. That is deliberate, and no such surface
 * uses this transport today.
 */
function toChatRequest(payload: Record<string, unknown>) {
  return {
    query: payload.query,
    // A first question opens the session, so an empty id must be omitted
    // entirely rather than sent as "".
    ...(payload.session_id ? { session_id: payload.session_id } : {}),
  };
}

/** One message of `GET …/{service_id}/sessions/{session_id}`. */
interface Nl2sqlWireMessage {
  chat_id?: string;
  role?: "user" | "assistant";
  message?: string;
  timestamp?: string;
  user_feedback?: string | null;
  trace_id?: string | null;
  is_answered?: boolean | null;
  debug_info?: Nl2sqlDebugInfo | null;
  graph_output?: Nl2sqlChartOutput | null;
  chart_output?: Nl2sqlChartOutput | null;
}

/**
 * The stored thread, in the shape `useChatStream` already maps.
 *
 * That mapping expects `debug_info` and `chart_output` as JSON strings — which
 * is how the dashboard service stores them — so the NL2SQL objects are
 * serialised back into it, with the `nl2sql` block added so the SQL and chart
 * panels light up on a reloaded conversation exactly as they do live.
 */
export async function fetchNl2sqlSession(
  serviceId: string,
  sessionId: string,
): Promise<{ conversation_data: unknown[] }> {
  const url = buildApiUrl(APIS.NL2SQL_SESSION, {
    service_id: serviceId,
    session_id: sessionId,
  });

  const response = await axios.get<{ conversation_data?: Nl2sqlWireMessage[] }>(
    url,
  );
  const wire = response.data.conversation_data;

  const conversation = (wire ?? []).map((message) => {
    const chart = message.graph_output ?? message.chart_output ?? null;
    const block = toNl2sqlBlock(message.debug_info, chart, message.message);
    return {
      chat_id: message.chat_id,
      role: message.role,
      message: message.message ?? "",
      timestamp: message.timestamp,
      user_feedback: message.user_feedback ?? null,
      // Both reach the run log; a stored turn that reports neither loses
      // nothing, and one that reports them keeps them across a reload.
      trace_id: message.trace_id ?? null,
      is_answered: message.is_answered ?? null,
      debug_info: message.debug_info
        ? JSON.stringify({
            ...message.debug_info,
            ...(block ? { nl2sql: block } : {}),
          })
        : null,
      chart_output: chart ? JSON.stringify({ nl2sql: chart }) : null,
    };
  });

  return { conversation_data: conversation };
}

/** One row of `GET …/{service_id}/sessions`. */
interface Nl2sqlWireSession {
  session_id: string;
  session_title?: string | null;
  created_time?: string | null;
  user_id?: string | null;
  from_chat_widget?: boolean | null;
}

/**
 * The agent's sessions, as the NL2SQL service lists them.
 *
 * This is the whole list for this product: the dashboard's `/sessions` route is
 * keyed by chat-registry ids and answers 403 for an `NL2SQL_…` agent, so asking
 * it as well only ever failed the load.
 *
 * `guests` maps onto `show_guests_session`, which is what the owner-only
 * monitoring tabs need — the visitors' and widget threads live in the same
 * store, distinguished by `from_chat_widget`.
 */
export async function fetchNl2sqlSessions(
  serviceId: string,
  options: { guests?: boolean } = {},
) {
  const url = buildApiUrl(APIS.NL2SQL_SESSIONS, { service_id: serviceId });
  const response = await axios.get<{ sessions?: Nl2sqlWireSession[] }>(url, {
    params: options.guests ? { show_guests_session: true } : undefined,
  });
  return (response.data.sessions ?? []).map((session) => ({
    session_id: session.session_id,
    session_title: session.session_title ?? "",
    created_time: session.created_time ?? "",
    user_id: session.user_id ?? null,
    from_chat_widget: Boolean(session.from_chat_widget),
  }));
}

/** `PATCH …/{service_id}/sessions/{session_id}` — renames one thread. */
export async function renameNl2sqlSession(
  serviceId: string,
  sessionId: string,
  title: string,
): Promise<{ message?: string }> {
  const url = buildApiUrl(APIS.NL2SQL_SESSION, {
    service_id: serviceId,
    session_id: sessionId,
  });
  const response = await axios.patch<{ message?: string }>(url, {
    session_title: title,
  });
  return response.data ?? {};
}

/** `DELETE …/{service_id}/sessions/{session_id}` — removes one thread. */
export async function deleteNl2sqlSession(
  serviceId: string,
  sessionId: string,
): Promise<{ message?: string }> {
  const url = buildApiUrl(APIS.NL2SQL_SESSION, {
    service_id: serviceId,
    session_id: sessionId,
  });
  const response = await axios.delete<{ message?: string }>(url);
  return response.data ?? {};
}

/**
 * Everything the shared chat hook needs to talk to the NL2SQL service instead
 * of the chat service. `null` service id → no transport, so a caller without a
 * resolved agent keeps the default behaviour rather than posting to a path with
 * "null" in it.
 */
export function nl2sqlChatTransport(
  serviceId: string | null | undefined,
): ChatStreamTransport | undefined {
  if (!serviceId) return undefined;

  return {
    url: `${buildApiUrl(APIS.NL2SQL_CHAT, { service_id: serviceId })}?stream=true`,
    eventPrefixes: ["data:", "full_metadata:"],
    buildBody: toChatRequest,
    adaptEvent: (event) => {
      const debug = (event.debug_info ?? null) as Nl2sqlDebugInfo | null;
      // The service mirrors the chart block under both names on a live turn and
      // has been seen to send only `graph_output` on a stored one — reading a
      // single spelling is one rename away from a chartless answer.
      const chart = (event.chart_output ??
        event.graph_output ??
        null) as Nl2sqlChartOutput | null;
      const block = toNl2sqlBlock(
        debug,
        chart,
        typeof event.response === "string" ? event.response : undefined,
      );
      return {
        ...event,
        ...(block ? { data: { nl2sql: block } } : {}),
      };
    },
    fetchSession: (sessionId) => fetchNl2sqlSession(serviceId, sessionId),
    /**
     * The live answer carries no `debug_info` unless the agent's saved config
     * asks for it, and it defaults to off — see `toChatRequest` on why this
     * request deliberately does not override that. The stored turn has the SQL,
     * the tables and the rows regardless, so a finished answer is reconciled
     * against it rather than leaving the reader to reload the page to see how
     * the answer was reached.
     */
    reconcileAfterStream: true,
  };
}

/** `toNl2sqlBlock`, for the tests that cover column naming. */
export const nl2sqlBlockForTest = (
  debug: Nl2sqlDebugInfo | null,
  chart: Nl2sqlChartOutput | null,
  answer?: string,
) => toNl2sqlBlock(debug, chart, answer);
