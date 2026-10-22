import { describe, expect, it, vi } from "vitest";

import {
  nl2sqlBlockForTest,
  nl2sqlChatTransport,
  tablesFromSql,
} from "../nl2sqlChat";

vi.mock("@/platform/utils/axios", () => ({
  default: { get: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

const AGENT = "NL2SQL_76CC79E1";

/** The payload the shared chat components build for the chat service. */
const chatServicePayload = {
  agent_id: AGENT,
  session_id: "",
  query: "orders by status",
  no_of_chunks: 3,
  use_user_info: false,
  stream: true,
};

function body(payload: Record<string, unknown>) {
  const transport = nl2sqlChatTransport(AGENT);
  return transport!.buildBody!(payload);
}

describe("nl2sqlChatTransport request body", () => {
  it("sends only the question when no session is open", () => {
    expect(body(chatServicePayload)).toEqual({ query: "orders by status" });
  });

  it("carries the session id once one exists", () => {
    expect(body({ ...chatServicePayload, session_id: "sess-1" })).toEqual({
      query: "orders by status",
      session_id: "sess-1",
    });
  });

  /**
   * The Settings → Answers bug: an explicit value in the body overrides the
   * agent's saved setting, so "Show sources", "Charts" and "Follow-up
   * questions" had no effect however they were saved. Omitting the fields is
   * what makes the saved configuration the single source of truth.
   */
  it("never overrides the agent's saved answer settings", () => {
    const sent = body({ ...chatServicePayload, chart_output: false });
    for (const field of [
      "debug_info",
      "chart_output",
      "follow_up",
      "allowed_charts",
    ]) {
      expect(sent).not.toHaveProperty(field);
    }
  });

  it("has no transport at all without a service id", () => {
    expect(nl2sqlChatTransport(null)).toBeUndefined();
  });
});

describe("tablesFromSql", () => {
  it("names the table a plain query read", () => {
    expect(
      tablesFromSql(
        "SELECT id, email FROM customers WHERE EXTRACT(MONTH FROM created_at) = 5 LIMIT 10",
      ),
    ).toEqual(["customers"]);
  });

  it("names every table a join read, without their aliases", () => {
    expect(
      tablesFromSql(
        "SELECT p.sku FROM products p JOIN order_items oi ON oi.product_id = p.id LEFT JOIN refunds r ON r.order_id = oi.order_id",
      ),
    ).toEqual(["products", "order_items", "refunds"]);
  });

  it("takes the table out of a schema-qualified name", () => {
    expect(tablesFromSql("SELECT * FROM public.orders")).toEqual(["orders"]);
  });

  it("has nothing to say about a query it cannot read", () => {
    expect(tablesFromSql("")).toEqual([]);
  });
});

describe("columns for a SELECT * result", () => {
  const dbOutput = JSON.stringify([
    ["ORD-1", "DELIVERED", 25],
    ["ORD-2", "PENDING", 11],
  ]);
  const answer = `Here are the orders:

| Order Number | Status | Total |
| --- | --- | --- |
| ORD-1 | DELIVERED | 25 |
| ORD-2 | PENDING | 11 |
`;

  it("names the columns from the answer's own table when the query says only *", () => {
    const block = nl2sqlBlockForTest(
      { sql_query: "SELECT * FROM orders LIMIT 10", db_output: dbOutput },
      null,
      answer,
    );
    expect(
      (block?.db_result as { columns: Array<{ name: string }> }).columns.map(
        (column) => column.name,
      ),
    ).toEqual(["Order Number", "Status", "Total"]);
  });

  it("keeps the query's own names when it has them", () => {
    const block = nl2sqlBlockForTest(
      {
        sql_query: "SELECT order_number, status, total FROM orders",
        db_output: dbOutput,
      },
      null,
      answer,
    );
    expect(
      (block?.db_result as { columns: Array<{ name: string }> }).columns.map(
        (column) => column.name,
      ),
    ).toEqual(["order_number", "status", "total"]);
  });

  /**
   * Seen on a reloaded thread, 2026-09-22: `SELECT status, COUNT(*)` names the
   * first column and leaves the second as `column_2`, and the card drew
   * "STATUS | COLUMN_2". Recovery only ran when every column was nameless.
   */
  it("names only the columns the query left nameless", () => {
    const block = nl2sqlBlockForTest(
      {
        sql_query: "SELECT status, COUNT(*) FROM orders GROUP BY status",
        db_output: JSON.stringify([
          ["PROCESSING", 3],
          ["CANCELLED", 13],
        ]),
      },
      null,
      `Here is the breakdown:

| Status | Count |
| --- | --- |
| PROCESSING | 3 |
| CANCELLED | 13 |
`,
    );
    const result = block?.db_result as {
      columns: Array<{ name: string }>;
      rows: Record<string, unknown>[];
    };
    expect(result.columns.map((column) => column.name)).toEqual([
      "status",
      "Count",
    ]);
    expect(result.rows[0]).toEqual({ status: "PROCESSING", Count: 3 });
  });

  it("leaves positional names alone when the answer's table is a different width", () => {
    const block = nl2sqlBlockForTest(
      { sql_query: "SELECT * FROM orders", db_output: dbOutput },
      null,
      "| Only | Two |\n| --- | --- |\n| a | b |",
    );
    expect(
      (block?.db_result as { columns: Array<{ name: string }> }).columns.map(
        (column) => column.name,
      ),
    ).toEqual(["column_1", "column_2", "column_3"]);
  });
});
