import { describe, expect, it } from "vitest";

import { stripResultTables } from "../stripResultTables";

const ANSWER = `## Users Created in May

The query returned the first 10 customers whose account was created in May:

| Email | First Name |
| --- | --- |
| neha.desai@gmail.com | Neha |
| paddychase@gmail.com | Paddy |

**Note:** The result is limited to 10 rows.`;

/** The card under `ANSWER`: the same two columns, the same two rows. */
const CARD = {
  columns: ["email", "first_name"],
  rows: [
    { email: "neha.desai@gmail.com", first_name: "Neha" },
    { email: "paddychase@gmail.com", first_name: "Paddy" },
  ],
};

describe("stripResultTables", () => {
  it("drops the table the result card already draws", () => {
    const out = stripResultTables(ANSWER, CARD);
    expect(out).not.toContain("neha.desai@gmail.com");
    expect(out).not.toContain("| --- |");
  });

  it("keeps every word of the prose around it", () => {
    const out = stripResultTables(ANSWER, CARD);
    expect(out).toContain("## Users Created in May");
    expect(out).toContain("created in May:");
    expect(out).toContain("**Note:** The result is limited to 10 rows.");
  });

  it("drops a restated table whose headers were renamed on the way out", () => {
    const renamed = ANSWER.replace(
      "| Email | First Name |",
      "| Address | Given Name |",
    );
    expect(stripResultTables(renamed, CARD)).not.toContain(
      "paddychase@gmail.com",
    );
  });

  it("drops a restatement that left the card's id column out", () => {
    // The answer printed two of the card's three columns back. Narrower than
    // the card, but every cell in it is a cell of the card.
    const narrower = `| Member | Missing Logs |
| --- | --- |
| Arijeet Nandy | **5** |`;
    const out = stripResultTables(narrower, {
      columns: ["id", "name", "missing_logs_count"],
      rows: [{ id: "f78e", name: "Arijeet Nandy", missing_logs_count: 5 }],
    });
    expect(out).not.toContain("Arijeet Nandy");
  });

  it("keeps a summary the answer built over the rows", () => {
    // The answer pivoted ten (name, date) rows into one row per member. The
    // card still holds the ten; this table is the reading of them, and is the
    // only place the summary exists.
    const summary = `## Missing Work Log Report

Below is a summary of the missing log dates for each member.

| **Member Name** | **Missing Log Dates** |
|-----------------|-----------------------|
| Shreyas | 2026-09-14, 2026-09-16 |
| soham sinha | 2026-09-14, 2026-09-15 |

> **Note:** The result set is limited to 10 rows.`;
    const out = stripResultTables(summary, {
      columns: ["id", "name", "missing_date"],
      rows: [
        { id: 1, name: "Shreyas", missing_date: "2026-09-14" },
        { id: 1, name: "Shreyas", missing_date: "2026-09-16" },
      ],
    });
    expect(out).toContain("| **Member Name** | **Missing Log Dates** |");
    expect(out).toContain("| Shreyas | 2026-09-14, 2026-09-16 |");
  });

  it("keeps the table when nothing is known about the card", () => {
    expect(stripResultTables(ANSWER)).toContain("neha.desai@gmail.com");
  });

  it("leaves an answer that has no table exactly as written", () => {
    const plain = "There are 42 customers.\n\n- one\n- two";
    expect(stripResultTables(plain, CARD)).toBe(plain);
  });

  it("does not mistake a pipe in a sentence for a table", () => {
    const prose = "Use a | b to split the field.\nIt is not a table.";
    expect(stripResultTables(prose, CARD)).toBe(prose);
  });

  it("drops more than one restated table", () => {
    const two = `First\n\n| a |\n| --- |\n| 1 |\n\nSecond\n\n| a |\n| --- |\n| 2 |\n\nEnd`;
    const out = stripResultTables(two, {
      columns: ["a"],
      rows: [{ a: 1 }, { a: 2 }],
    });
    expect(out).toContain("First");
    expect(out).toContain("Second");
    expect(out).toContain("End");
    expect(out).not.toContain("| 1 |");
    expect(out).not.toContain("| 2 |");
  });
});
