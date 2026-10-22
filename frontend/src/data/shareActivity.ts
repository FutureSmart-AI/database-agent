"use client";

import { useQuery } from "@tanstack/react-query";

import { buildApiUrl } from "@/platform/utils";
import axios from "@/platform/utils/axios";

import { APIS } from "./api";

/**
 * What other people asked, for Share → Activity.
 *
 * Read from the query log, `GET …/analytics/queries`, and NOT from
 * `GET …/sessions`. The session list answers `{"sessions": []}` even for an
 * agent asked a question a moment ago — the same service gap the Conversations
 * list already carries a `localStorage` crutch for (see `openedSessions.ts`) —
 * so a screen whose whole job is "what did other people ask" cannot be built on
 * it. The query log is written per answered question and carries who asked
 * (`user_id`), whether it came from the website bubble (`from_widget`) and the
 * session it belongs to, which is everything this screen shows.
 *
 * The session list is still merged in on top, so a conversation the service does
 * list is not missing here either; the two are keyed by `session_id`.
 */

/** One logged question, narrowed to the fields this screen reads. */
interface QueryLogRow {
  chat_id: string;
  session_id: string | null;
  user_id: string | null;
  timestamp: string;
  query: string;
  from_widget?: boolean;
  status?: string;
  outcome?: string;
  metrics?: { latency_ms?: number } | null;
}

/** A conversation as the Activity list shows it. */
export interface ActivityRow {
  /** `session_id` when the log carries one, else the single question's id. */
  id: string;
  /** Present only when the thread can be read back in full. */
  sessionId: string | null;
  who: string | null;
  fromWidget: boolean;
  /** The first question asked, which is what the conversation is about. */
  title: string;
  /** How many questions were asked in it. */
  asked: number;
  /** Epoch ms of the most recent question. */
  at: number;
  /** Slowest answer in the conversation, in ms, when the log measured one. */
  latency: number | null;
}

const epoch = (value: string | undefined) =>
  value ? Date.parse(value) || 0 : 0;

/**
 * Folds logged questions into one row per conversation.
 *
 * Rows arrive newest-first or slowest-first depending on the sort asked for, so
 * order is never assumed: the title comes from the OLDEST question in the group
 * (what the conversation opened with) and `at` from the newest.
 */
export function groupQueries(rows: QueryLogRow[]): ActivityRow[] {
  const byConversation = new Map<
    string,
    { first: QueryLogRow; row: ActivityRow }
  >();
  rows.forEach((entry) => {
    const id = entry.session_id ?? entry.chat_id;
    if (!id) return;
    const at = epoch(entry.timestamp);
    const latency = entry.metrics?.latency_ms ?? null;
    const existing = byConversation.get(id);
    if (!existing) {
      byConversation.set(id, {
        first: entry,
        row: {
          id,
          sessionId: entry.session_id ?? null,
          who: entry.user_id ?? null,
          fromWidget: Boolean(entry.from_widget),
          title: entry.query,
          asked: 1,
          at,
          latency,
        },
      });
      return;
    }
    existing.row.asked += 1;
    existing.row.at = Math.max(existing.row.at, at);
    if (latency !== null)
      existing.row.latency = Math.max(existing.row.latency ?? 0, latency);
    // An earlier question replaces the title; a later one never does.
    if (at && at < epoch(existing.first.timestamp)) {
      existing.first = entry;
      existing.row.title = entry.query;
    }
    existing.row.who = existing.row.who ?? entry.user_id ?? null;
    existing.row.fromWidget =
      existing.row.fromWidget || Boolean(entry.from_widget);
  });
  return [...byConversation.values()].map((entry) => entry.row);
}

/** The window the list is looking at; `null` days means everything there is. */
export interface ActivityWindow {
  days: number | null;
}

/**
 * The service caps this route at 100 rows and its `sort` vocabulary is not
 * documented, so the newest 100 are taken with the default sort and ordered
 * here. A busier agent than that needs paging, which the list does not offer
 * yet — `truncated` says so rather than quietly showing a slice.
 */
const LIMIT = 100;

export function useActivityQueries(
  serviceId: string | undefined,
  { days }: ActivityWindow,
) {
  return useQuery({
    queryKey: ["share-activity", serviceId, days],
    enabled: Boolean(serviceId),
    queryFn: async (): Promise<{
      rows: ActivityRow[];
      truncated: boolean;
    }> => {
      const url = buildApiUrl(APIS.ANALYTICS_QUERIES, {
        agent_id: serviceId as string,
      });
      // An explicit range rather than `period`: its vocabulary is undocumented,
      // and start_date + end_date is documented to override it either way.
      const end = new Date();
      const start = new Date(days === null ? 0 : end.getTime() - days * 864e5);
      const response = await axios.get<{
        queries?: QueryLogRow[];
        total_matching?: number;
      }>(url, {
        params: {
          include_node_data: false,
          limit: LIMIT,
          start_date: start.toISOString(),
          end_date: new Date(end.getTime() + 864e5).toISOString(),
        },
      });
      const logged = response.data.queries ?? [];
      return {
        rows: groupQueries(logged),
        // The envelope's own count, so "there is more than this" is the
        // service's answer rather than an inference from a full page.
        truncated: (response.data.total_matching ?? logged.length) > LIMIT,
      };
    },
  });
}
