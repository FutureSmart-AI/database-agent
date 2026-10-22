"use client";

/**
 * Conversations this browser opened, remembered until the service lists them.
 *
 * `GET /nl2sql/api/v1/agents/{service_id}/sessions` answers `{"sessions": []}`
 * even for an agent that was asked a question a moment ago — the session itself
 * is readable by id, it is simply in no list. Without this, a thread answered
 * before a refresh was gone from Conversations afterwards, and the list moved
 * the selection to some older conversation.
 *
 * So the ids opened here are kept alongside the service's own list. Each is
 * dropped as soon as the service returns it, which makes this disappear on its
 * own once the list is fixed — nothing else reads this store, and the thread it
 * points at lives in the service either way.
 */

export interface OpenedSession {
  session_id: string;
  session_title: string;
  created_time: string;
}

/** Enough for the list's own paging; the oldest fall off beyond it. */
const LIMIT = 50;
/** A session older than this is the service's to list, not this store's. */
const MAX_AGE_MS = 30 * 24 * 60 * 60 * 1000;

const keyFor = (serviceId: string) => `nl2sql:opened-sessions:${serviceId}`;

const isRow = (value: unknown): value is OpenedSession =>
  typeof value === "object" &&
  value !== null &&
  typeof (value as OpenedSession).session_id === "string";

/**
 * Reads the store. Returns nothing when there is no `localStorage` — this app
 * is a static export, so the first render also happens on the build machine.
 */
export function readOpenedSessions(
  serviceId: string | null | undefined,
  now = Date.now(),
): OpenedSession[] {
  if (!serviceId || typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(keyFor(serviceId));
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(isRow).filter((row) => {
      const at = Date.parse(row.created_time);
      return Number.isNaN(at) || now - at < MAX_AGE_MS;
    });
  } catch {
    // A corrupt or blocked store must not take the conversation list down.
    return [];
  }
}

export function writeOpenedSessions(
  serviceId: string | null | undefined,
  sessions: OpenedSession[],
): void {
  if (!serviceId || typeof window === "undefined") return;
  try {
    window.localStorage.setItem(
      keyFor(serviceId),
      JSON.stringify(sessions.slice(0, LIMIT)),
    );
  } catch {
    // Private mode or a full quota: the list still works for this page view.
  }
}
