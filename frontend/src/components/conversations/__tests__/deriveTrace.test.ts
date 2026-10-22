import { describe, expect, it } from "vitest";

import type { Nl2sqlView } from "@/platform/components/conversations/nl2sql/normalizeNl2sql";

import { deriveTrace, sqlSummary } from "../deriveTrace";

const view = (over: Partial<Nl2sqlView> = {}): Nl2sqlView => ({
  tablesUsed: [],
  rowCountIsPreview: false,
  ...over,
});

describe("deriveTrace", () => {
  it("shows Thinking alone before the first chunk arrives", () => {
    expect(deriveTrace({ loading: true, answer: "", view: null })).toEqual([
      { key: "thinking", label: "Thinking", state: "active" },
    ]);
  });

  it("completes Thinking and opens Writing once text streams", () => {
    const rows = deriveTrace({
      loading: true,
      answer: "The query",
      view: null,
    });
    expect(rows.map((row) => [row.key, row.state])).toEqual([
      ["thinking", "done"],
      ["writing", "active"],
    ]);
  });

  it("reports a failure as its own row, carrying the sanitised message", () => {
    const rows = deriveTrace({
      loading: false,
      answer: "",
      view: null,
      error: "The agent could not reach the database.",
    });
    expect(rows[rows.length - 1]).toEqual({
      key: "failed",
      label: "Run failed",
      detail: "The agent could not reach the database.",
      state: "failed",
    });
  });

  it("draws nothing for an answer that ran no query", () => {
    expect(
      deriveTrace({ loading: false, answer: "Hello", view: null }),
    ).toEqual([]);
  });

  it("reports one completed row per fact the run produced", () => {
    const rows = deriveTrace({
      loading: false,
      answer: "done",
      view: view({
        sqlQuery: "SELECT *\n  FROM customers\n LIMIT 10",
        tablesUsed: ["customers"],
        executionTimeMs: 1240,
        rowCount: 10,
      }),
    });
    expect(rows).toEqual([
      {
        key: "sql",
        label: "Generated SQL",
        detail: "SELECT * FROM customers LIMIT 10",
        state: "done",
      },
      {
        key: "tables",
        label: "Read table",
        detail: "customers",
        state: "done",
      },
      { key: "exec", label: "Executed", detail: "1.24s", state: "done" },
      {
        key: "rows",
        label: "Returned 10 rows",
        detail: undefined,
        state: "done",
      },
    ]);
  });

  it("omits rows for facts the run did not report", () => {
    const rows = deriveTrace({
      loading: false,
      answer: "done",
      view: view({ sqlQuery: "SELECT 1" }),
    });
    expect(rows.map((row) => row.key)).toEqual(["sql"]);
  });

  it("marks a row count that is only the preview", () => {
    const rows = deriveTrace({
      loading: false,
      answer: "done",
      view: view({ rowCount: 10, rowCountIsPreview: true }),
    });
    expect(rows[0].detail).toBe("preview");
  });

  it("pluralises tables and sub-second timings", () => {
    const rows = deriveTrace({
      loading: false,
      answer: "done",
      view: view({ tablesUsed: ["orders", "customers"], executionTimeMs: 320 }),
    });
    expect(rows[0].label).toBe("Read tables");
    expect(rows[0].detail).toBe("orders, customers");
    expect(rows[1].detail).toBe("320ms");
  });
});

describe("sqlSummary", () => {
  it("collapses whitespace onto one line", () => {
    expect(sqlSummary("SELECT *\n  FROM t")).toBe("SELECT * FROM t");
  });

  it("truncates past the limit", () => {
    expect(sqlSummary("SELECT abcdefghij FROM t", 12)).toBe("SELECT abcd…");
  });
});
