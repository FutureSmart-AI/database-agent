import { describe, expect, it } from "vitest";

import { groupQueries } from "../shareActivity";

/**
 * Folding the query log into conversations. The log is per question, and the
 * Activity list is per conversation, so this is where "3 questions asked, last
 * one an hour ago, opened with …" comes from.
 */

const t = (msAgo: number) => new Date(Date.now() - msAgo).toISOString();

const row = (over: Record<string, unknown> = {}) =>
  ({
    chat_id: "c1",
    session_id: "s1",
    user_id: "analyst@acme-retail.com",
    timestamp: t(864e5),
    query: "Top 5 customers by total spend",
    from_widget: false,
    metrics: { latency_ms: 1200 },
    ...over,
  }) as Parameters<typeof groupQueries>[0][number];

describe("groupQueries", () => {
  it("makes one row per session and counts the questions in it", () => {
    const rows = groupQueries([
      row({ chat_id: "c1" }),
      row({ chat_id: "c2", timestamp: t(3600e3) }),
      row({ chat_id: "c3", session_id: "s2", query: "Revenue by month" }),
    ]);
    expect(rows).toHaveLength(2);
    const first = rows.find((entry) => entry.id === "s1");
    expect(first?.asked).toBe(2);
    expect(rows.find((entry) => entry.id === "s2")?.asked).toBe(1);
  });

  it("titles a conversation with the question it opened on, whatever the order", () => {
    const rows = groupQueries([
      // Newest first, as the log's default sort can return it.
      row({ chat_id: "c2", timestamp: t(3600e3), query: "And by region?" }),
      row({ chat_id: "c1", timestamp: t(7200e3), query: "Revenue by month" }),
    ]);
    expect(rows[0].title).toBe("Revenue by month");
  });

  it("dates a conversation by its most recent question", () => {
    const recent = t(3600e3);
    const rows = groupQueries([
      row({ chat_id: "c1", timestamp: t(864e5) }),
      row({ chat_id: "c2", timestamp: recent }),
    ]);
    expect(rows[0].at).toBe(Date.parse(recent));
  });

  it("keeps the slowest answer in the conversation", () => {
    const rows = groupQueries([
      row({ chat_id: "c1", metrics: { latency_ms: 900 } }),
      row({ chat_id: "c2", metrics: { latency_ms: 4200 } }),
    ]);
    expect(rows[0].latency).toBe(4200);
  });

  it("marks a conversation as the bubble's if any of its questions came from it", () => {
    const rows = groupQueries([
      row({ chat_id: "c1", from_widget: false, user_id: null }),
      row({ chat_id: "c2", from_widget: true, user_id: null }),
    ]);
    expect(rows[0].fromWidget).toBe(true);
    expect(rows[0].who).toBeNull();
  });

  it("names the asker from whichever question carries one", () => {
    const rows = groupQueries([
      row({ chat_id: "c1", user_id: null }),
      row({ chat_id: "c2", user_id: "ops.lead@acme-retail.com" }),
    ]);
    expect(rows[0].who).toBe("ops.lead@acme-retail.com");
  });

  it("still lists a question the log filed under no session", () => {
    const rows = groupQueries([row({ session_id: null, chat_id: "c9" })]);
    expect(rows[0].id).toBe("c9");
    // Nothing to open: the thread is only readable by session id.
    expect(rows[0].sessionId).toBeNull();
  });

  it("drops a row with neither id rather than grouping it under undefined", () => {
    const rows = groupQueries([
      row({ session_id: null, chat_id: "" }),
      row({ chat_id: "c1" }),
    ]);
    expect(rows).toHaveLength(1);
    expect(rows[0].id).toBe("s1");
  });

  it("returns nothing for an empty log", () => {
    expect(groupQueries([])).toEqual([]);
  });
});
