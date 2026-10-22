import { describe, expect, it } from "vitest";

import type { ConversationSession } from "@/platform/types/session";

import { filterSessions, groupSessions } from "../groupSessions";

const NOW = new Date(2026, 8, 2, 12, 0, 0);

/** Local-time timestamp: the buckets mean calendar days where the user is. */
const at = (year: number, month: number, day: number, hour = 12): string =>
  new Date(year, month, day, hour).toISOString();

const session = (id: string, created: string): ConversationSession => ({
  session_id: id,
  session_title: id,
  created_time: created,
});

describe("groupSessions", () => {
  it("buckets by calendar day, not by elapsed hours", () => {
    // 23:00 yesterday is 13 hours ago but belongs under Yesterday.
    const groups = groupSessions(
      [
        session("now", at(2026, 8, 2, 9)),
        session("lateYesterday", at(2026, 8, 1, 23)),
      ],
      NOW,
    );
    expect(groups.map((group) => group.label)).toEqual(["Today", "Yesterday"]);
    expect(groups[1].items[0].session_id).toBe("lateYesterday");
  });

  it("separates the last week from older threads", () => {
    const groups = groupSessions(
      [
        session("week", at(2026, 7, 29, 10)),
        session("old", at(2026, 6, 1, 10)),
      ],
      NOW,
    );
    expect(groups.map((group) => group.label)).toEqual([
      "Previous 7 days",
      "Older",
    ]);
  });

  it("drops empty buckets", () => {
    const groups = groupSessions([session("a", at(2026, 8, 2, 1))], NOW);
    expect(groups).toHaveLength(1);
    expect(groups[0].label).toBe("Today");
  });

  it("keeps a session whose created_time cannot be parsed", () => {
    const groups = groupSessions(
      [{ session_id: "x", session_title: "x", created_time: "" }],
      NOW,
    );
    expect(groups).toEqual([
      {
        label: "Older",
        items: [{ session_id: "x", session_title: "x", created_time: "" }],
      },
    ]);
  });

  it("preserves the order it was given inside a bucket", () => {
    const groups = groupSessions(
      [
        session("first", at(2026, 8, 2, 9)),
        session("second", at(2026, 8, 2, 10)),
      ],
      NOW,
    );
    expect(groups[0].items.map((item) => item.session_id)).toEqual([
      "first",
      "second",
    ]);
  });
});

describe("filterSessions", () => {
  const rows = [session("Refunds by region", at(2026, 8, 2, 9))];

  it("matches titles case-insensitively", () => {
    expect(filterSessions(rows, "REFUNDS")).toHaveLength(1);
  });

  it("returns everything for a blank query", () => {
    expect(filterSessions(rows, "   ")).toBe(rows);
  });

  it("returns nothing when no title matches", () => {
    expect(filterSessions(rows, "orders")).toHaveLength(0);
  });
});
