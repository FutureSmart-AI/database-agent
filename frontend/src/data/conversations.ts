"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { streamSSERequest, type SSEError } from "@/platform/chat-core";
import { buildApiUrl } from "@/platform/utils";
import axios from "@/platform/utils/axios";

import { APIS } from "./api";

/**
 * Conversations, live.
 *
 * `GET /nl2sql/api/v1/agents/{agent_id}/sessions` lists sessions and
 * `GET /nl2sql/api/v1/agents/{agent_id}/sessions/{session_id}` returns their
 * `conversation_data`:
 * alternating user/assistant messages, each assistant turn carrying its
 * `debug_info` (latency, the SQL it ran) and `chart_output`.
 */

export interface SessionRow {
  session_id: string;
  agent_id: string;
  user_id: string | null;
  session_title: string;
  display_message: string;
  from_chat_widget: boolean;
  created_time: string;
}

/** One message as the session endpoint returns it. */
interface WireMessage {
  chat_id: string;
  role: "user" | "assistant";
  message: string;
  timestamp: string;
  /** JSON string: `{ latency_ms, sources, steps, type }`. */
  debug_info: string | null;
  user_feedback?: string | null;
  /** JSON string: `{ nl2sql: { chart_suggestion, chart_data } }`. */
  chart_output?: string | null;
}

export interface ChartPoint {
  label: string;
  value: number;
}

/** One question and the answer to it, as a view renders it. */
export interface Turn {
  chat_id: string;
  question: string;
  answer: string;
  timestamp: string;
  /** Thumbs the user left, when they left one. */
  feedback: "up" | "down" | null;
  latency: number | null;
  sql: string | null;
  tables: string[];
  chart: { title: string; data: ChartPoint[] } | null;
  raw: unknown;
}

/** `debug_info` and `chart_output` arrive as JSON strings. */
function parse<T>(value: string | null | undefined): T | null {
  if (!value) return null;
  try {
    return JSON.parse(value) as T;
  } catch {
    return null;
  }
}

interface DebugInfo {
  latency_ms?: number;
  sql_query?: string;
  selected_tables?: string[];
  sources?: Array<{ sql_query?: string; table?: string }>;
  steps?: unknown[];
}

interface ChartOutput {
  nl2sql?: {
    chart_suggestion?: string;
    chart_data?: {
      data?: Array<{
        index?: string;
        label?: string;
        value?: number;
        segments?: Array<{ category: string; value: number }>;
      }>;
    };
  };
}

/** Flattens the chart the answer carried into the app's bar-chart shape. */
function toChart(output: ChartOutput | null): Turn["chart"] {
  const chart = output?.nl2sql;
  const rows = chart?.chart_data?.data;
  if (!chart || !rows?.length) return null;

  const points: ChartPoint[] = [];
  for (const row of rows) {
    if (row.segments?.length) {
      for (const segment of row.segments) {
        points.push({
          label: `${row.index ?? row.label ?? ""} · ${segment.category}`,
          value: segment.value,
        });
      }
    } else if (typeof row.value === "number") {
      points.push({ label: row.index ?? row.label ?? "", value: row.value });
    }
  }
  return points.length
    ? { title: chart.chart_suggestion ?? "Chart", data: points }
    : null;
}

/** Pairs the flat message list into question/answer turns. */
function toTurns(messages: WireMessage[]): Turn[] {
  const turns: Turn[] = [];
  for (let index = 0; index < messages.length; index++) {
    const message = messages[index];
    if (message.role !== "user") continue;
    const answer =
      messages[index + 1]?.role === "assistant" ? messages[index + 1] : null;
    const debug = parse<DebugInfo>(answer?.debug_info);
    const feedback = answer?.user_feedback;

    turns.push({
      chat_id: message.chat_id,
      question: message.message,
      answer: answer?.message ?? "",
      timestamp: message.timestamp,
      feedback:
        feedback === "positive" || feedback === "up"
          ? "up"
          : feedback === "negative" || feedback === "down"
            ? "down"
            : null,
      latency: debug?.latency_ms ?? null,
      sql: debug?.sql_query ?? debug?.sources?.[0]?.sql_query ?? null,
      tables:
        debug?.selected_tables ??
        (debug?.sources ?? [])
          .map((source) => source.table)
          .filter((table): table is string => Boolean(table)),
      chart: toChart(parse<ChartOutput>(answer?.chart_output)),
      raw: { debug_info: debug, chart_output: answer?.chart_output ?? null },
    });
  }
  return turns;
}

/**
 * Sessions shown by the three conversation tabs.
 *
 * Personal history deliberately uses the normal sessions endpoint.  The admin
 * endpoint is for monitoring other users and widget visitors, and using it for
 * the default tab made a visitor's thread look like one the owner could reply
 * to.
 */
export function useSessions(
  agentId: string | undefined,
  source: "mine" | "users" | "widget",
) {
  return useQuery({
    queryKey: ["sessions", agentId, source],
    enabled: Boolean(agentId),
    queryFn: async (): Promise<SessionRow[]> => {
      const response = await axios.get<{ sessions: SessionRow[] }>(
        buildApiUrl(APIS.NL2SQL_SESSIONS, { service_id: agentId as string }),
        {
          params: source === "mine" ? undefined : { show_guests_session: true },
        },
      );
      return (response.data.sessions ?? []).filter((session) =>
        source === "widget"
          ? session.from_chat_widget
          : !session.from_chat_widget,
      );
    },
  });
}

/** One session's turns. */
export function useSessionTurns(
  agentId: string | undefined,
  sessionId: string | null,
) {
  return useQuery({
    queryKey: ["session", agentId, sessionId],
    enabled: Boolean(agentId && sessionId),
    queryFn: async (): Promise<Turn[]> => {
      const url = buildApiUrl(APIS.NL2SQL_SESSION, {
        service_id: agentId as string,
        session_id: sessionId as string,
      });
      const response = await axios.get<{ conversation_data: WireMessage[] }>(
        url,
      );
      return toTurns(response.data.conversation_data ?? []);
    },
  });
}

export interface ChatResponse {
  response: string;
  session_id: string;
  chat_id: string;
  follow_up?: string[];
  debug_info?: DebugInfo;
}

/**
 * Asks the NL2SQL agent directly over SSE.
 *
 * The endpoint streams: it answers `text/event-stream` and reports the session
 * it opened in the stream (and in `x-session-id`). Reading it as a plain JSON
 * POST returned no `session_id`, so a first question never attached to a
 * session and none of the asking showed up under Conversations. This uses the
 * same `streamSSERequest` transport and the same request fields as the agent
 * UI's chat, so the two surfaces behave identically.
 *
 * `onChunk` receives the answer as it accumulates, for rendering it live.
 */
export function useAsk(
  agentId: string | undefined,
  onChunk?: (text: string) => void,
) {
  const client = useQueryClient();

  return useMutation({
    mutationFn: async (input: {
      query: string;
      sessionId: string | null;
    }): Promise<ChatResponse> => {
      let answer = "";
      let chatId = "";
      let sessionId = input.sessionId ?? "";
      let debug: DebugInfo | undefined;
      let followUp: string[] | undefined;
      let failure: SSEError | null = null;
      /** An `error` event: the run broke after the stream had already opened. */
      let streamError: string | null = null;

      const { sessionId: headerSession } = await streamSSERequest({
        url: `${buildApiUrl(APIS.NL2SQL_CHAT, { service_id: agentId as string })}?stream=true`,
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          accept: "text/event-stream",
        },
        credentials: "include",
        // `chart_output`, `debug_info`, `follow_up` and `allowed_charts` are
        // omitted on purpose: an explicit value in the body overrides the
        // agent's saved setting, so sending them here would make Settings →
        // Answers inert exactly as it did on the dashboard chat. See
        // `toChatRequest` in `./nl2sqlChat`.
        body: JSON.stringify({
          session_id: input.sessionId,
          query: input.query,
        }),
        // A cold model run against a large schema is slow to start; this is the
        // idle timeout, so a stream that keeps producing is never cut off.
        timeoutMs: 180_000,
        onEvent: (event) => {
          // A failed run answers 200 and reports itself inside the stream, as
          // `{"error": …}`. Without this the error text was accumulated as if it
          // were the answer, so a broken run looked like a successful one.
          const reported = (event as { error?: unknown }).error;
          if (typeof reported === "string" && reported) {
            streamError = reported;
            return;
          }
          if (event.response != null) answer = event.response;
          else if (event.chunk != null) answer += event.chunk;
          if (event.chat_id) chatId = event.chat_id;
          if (event.session_id) sessionId = event.session_id;
          if (event.debug_info != null) debug = event.debug_info as DebugInfo;
          if (event.follow_up) followUp = event.follow_up;
          onChunk?.(answer);
        },
        onComplete: () => {},
        onError: (error) => {
          failure = error;
        },
      });

      if (failure) throw new Error((failure as SSEError).message);
      if (streamError) throw new Error(streamError);

      return {
        response: answer,
        session_id: sessionId || headerSession || "",
        chat_id: chatId,
        follow_up: followUp,
        debug_info: debug,
      };
    },
    onSuccess: (data) => {
      client.invalidateQueries({ queryKey: ["sessions", agentId] });
      client.invalidateQueries({
        queryKey: ["session", agentId, data.session_id],
      });
    },
  });
}

/**
 * `POST /nl2sql/api/v1/agents/{agent_id}/feedback` — thumbs on one answer.
 *
 * The route is collection-level and takes all three ids in the body, with the
 * verdict as a boolean. (chat-core's `FeedbackPayload` type says
 * `thumbs_up`/`thumbs_down` and omits `agent_id`; the deployed API rejects
 * that with a 422 — this matches what it actually accepts.)
 */
export function useFeedback(agentId: string | undefined) {
  const client = useQueryClient();

  return useMutation({
    mutationFn: async (input: {
      sessionId: string;
      chatId: string;
      userQuery: string;
      generatedQuery: string;
      /** True is a thumbs up. */
      positive: boolean;
    }) => {
      await axios.post(
        buildApiUrl(APIS.NL2SQL_FEEDBACK, { service_id: agentId as string }),
        {
          chat_id: input.chatId,
          session_id: input.sessionId,
          user_query: input.userQuery,
          generated_query: input.generatedQuery,
          label: input.positive ? "correct" : "incorrect",
        },
      );
    },
    onSuccess: (_result, input) => {
      client.invalidateQueries({
        queryKey: ["session", agentId, input.sessionId],
      });
    },
  });
}

export type ReportCategory =
  "wrong_answer" | "wrong_chart" | "lost_context" | "error" | "slow" | "other";

/**
 * `POST /nl2sql/api/v1/agents/{agent_id}/reports` — report a problem with one
 * answer. Only the person who asked can; the service snapshots the
 * conversation up to that answer and returns the report id.
 */
export function useReportAnswer(agentId: string | undefined) {
  return useMutation({
    mutationFn: async (input: {
      sessionId: string;
      chatId: string;
      category: ReportCategory;
      note: string;
      expected?: string;
    }) => {
      const response = await axios.post<{ report_id: string; status: string }>(
        buildApiUrl(APIS.NL2SQL_REPORTS, { service_id: agentId as string }),
        {
          session_id: input.sessionId,
          chat_id: input.chatId,
          category: input.category,
          note: input.note.trim(),
          expected: input.expected?.trim() || null,
        },
      );
      return response.data;
    },
  });
}
