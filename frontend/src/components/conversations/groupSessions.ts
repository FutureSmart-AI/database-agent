import type { ConversationSession } from "@/platform/types/session";

/** A dated bucket of sessions, in the order the sidebar draws them. */
export interface SessionGroup {
  label: string;
  items: ConversationSession[];
}

const DAY_MS = 24 * 60 * 60 * 1000;

/** Midnight local time for a date, so "yesterday" means the calendar day. */
function startOfDay(date: Date): number {
  return new Date(
    date.getFullYear(),
    date.getMonth(),
    date.getDate(),
  ).getTime();
}

/**
 * Buckets sessions into Today / Yesterday / Previous 7 days / Older.
 *
 * Sessions with an unparseable `created_time` are kept rather than dropped —
 * the NL2SQL service has returned rows without one, and a conversation the user
 * can see in the list is better than a thread that silently disappears. They
 * sort last, under Older.
 */
export function groupSessions(
  sessions: ConversationSession[],
  now: Date = new Date(),
): SessionGroup[] {
  const today = startOfDay(now);
  const buckets: SessionGroup[] = [
    { label: "Today", items: [] },
    { label: "Yesterday", items: [] },
    { label: "Previous 7 days", items: [] },
    { label: "Older", items: [] },
  ];

  for (const session of sessions) {
    const time = Date.parse(session.created_time ?? "");
    if (Number.isNaN(time)) {
      buckets[3].items.push(session);
      continue;
    }
    const day = startOfDay(new Date(time));
    if (day === today) buckets[0].items.push(session);
    else if (day === today - DAY_MS) buckets[1].items.push(session);
    else if (day > today - 7 * DAY_MS) buckets[2].items.push(session);
    else buckets[3].items.push(session);
  }

  return buckets.filter((bucket) => bucket.items.length > 0);
}

/** Case-insensitive title match, used by the sidebar's search box. */
export function filterSessions(
  sessions: ConversationSession[],
  query: string,
): ConversationSession[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return sessions;
  return sessions.filter((session) =>
    (session.session_title ?? "").toLowerCase().includes(needle),
  );
}
