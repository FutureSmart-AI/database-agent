import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { fetchNl2sqlSession } from "@/data/nl2sqlChat";
import { normalizeNl2sql } from "@/platform/components/conversations/nl2sql/normalizeNl2sql";
import axios from "@/platform/utils/axios";

import FullLogs from "../FullLogs";
import { readRunLog } from "../runLog";

vi.mock("@/platform/utils/axios", () => ({ default: { get: vi.fn() } }));

const SQL =
  "SELECT c.customer_id, SUM(o.total_amount) AS total_spend FROM customers c JOIN orders o USING (customer_id) GROUP BY 1 ORDER BY 2 DESC LIMIT 5";

/** The `usage` block the hosted service returned for a real sample-data answer. */
const USAGE = {
  latency_ms: 11140,
  input_tokens: 9861,
  output_tokens: 399,
  estimated_cost_usd: 0.010929,
  cost_complete: true,
  price_table: "openai-standard-2026-10-25",
  nodes: [
    {
      node: "router",
      provider: "openai",
      model: "gpt-6-luna",
      input_tokens: 1630,
      output_tokens: 52,
      latency_ms: 1290,
      calls: 1,
      estimated_cost_usd: 0.000189,
    },
    {
      node: "select_table",
      provider: "openai",
      model: "gpt-6.1-sol",
      input_tokens: 734,
      output_tokens: 24,
      latency_ms: 2236,
      calls: 1,
      estimated_cost_usd: 0.001708,
    },
    {
      node: "sql_gen",
      provider: "openai",
      model: "gpt-6.1-sol",
      input_tokens: 3714,
      output_tokens: 112,
      latency_ms: 2091,
      calls: 1,
      estimated_cost_usd: 0.008548,
    },
    {
      node: "sql_exec",
      provider: null,
      model: null,
      input_tokens: 0,
      output_tokens: 0,
      latency_ms: 37,
      calls: 1,
      estimated_cost_usd: null,
    },
    {
      node: "check_pandas",
      provider: "openai",
      model: "gpt-6-luna",
      input_tokens: 635,
      output_tokens: 54,
      latency_ms: 1725,
      calls: 1,
      estimated_cost_usd: 0.0000905,
    },
    {
      node: "final_answer",
      provider: "openai",
      model: "gpt-6-luna",
      input_tokens: 1969,
      output_tokens: 98,
      latency_ms: 1888,
      calls: 1,
      estimated_cost_usd: 0.0002459,
    },
    {
      node: "other_calls",
      provider: "openai",
      model: "gpt-6-luna",
      input_tokens: 1179,
      output_tokens: 59,
      latency_ms: null,
      calls: 1,
      estimated_cost_usd: 0.0001474,
    },
  ],
};

/** A saved turn read back through the real stored-session adapter, then logged. */
async function reopened(usage: unknown) {
  vi.mocked(axios.get).mockResolvedValueOnce({
    data: {
      conversation_data: [
        {
          role: "assistant",
          message: "Lucas Thompson spent the most.",
          debug_info: { query: "Top 5 customers by spend?", sql_query: SQL },
          usage,
        },
      ],
    },
  });
  const session = await fetchNl2sqlSession("NL2SQL_TEST", "saved-session");
  const wire = session.conversation_data[0] as { debug_info: string };
  const debug = JSON.parse(wire.debug_info);
  const message = { debug_info: debug, data: { nl2sql: debug.nl2sql } };
  const log = readRunLog({ message, view: normalizeNl2sql(message) });
  if (!log) throw new Error("No run log");
  render(<FullLogs log={log} />);
  fireEvent.click(screen.getByRole("button", { name: /Full logs/ }));
  return log;
}

describe("Full logs cost by operation", () => {
  it("shows a reopened answer's every operation, its model and a total that matches", async () => {
    const log = await reopened(USAGE);
    expect(log.partial).toBe(false);
    const table = screen.getByRole("table", { name: "Cost by operation" });
    const rows = within(table).getAllByRole("row");
    // header + seven operations + total
    expect(rows).toHaveLength(9);
    const row = (name: string) =>
      within(table).getByRole("rowheader", { name: new RegExp(name) })
        .parentElement as HTMLElement;
    expect(
      within(row("Routed the question")).getByText("gpt-6-luna"),
    ).toBeInTheDocument();
    expect(
      within(row("Wrote the query")).getByText("gpt-6.1-sol"),
    ).toBeInTheDocument();
    expect(
      within(row("Wrote the query")).getByText("≈$0.0085"),
    ).toBeInTheDocument();
    expect(
      within(row("Checked the result")).getByText("1.73s"),
    ).toBeInTheDocument();
    expect(
      within(row("Other model calls")).getByText("1,179 in / 59 out"),
    ).toBeInTheDocument();
    expect(within(row("Ran the query")).getByText("37ms")).toBeInTheDocument();
    expect(within(row("Total")).getByText("≈$0.0109")).toBeInTheDocument();
    expect(within(row("Total")).getByText("10,260 tokens")).toBeInTheDocument();
  });

  it("names the model on each step that made a call", async () => {
    await reopened(USAGE);
    const steps = screen.getByRole("list");
    const query = within(steps)
      .getByText("Wrote the query")
      .closest("li") as HTMLElement;
    expect(within(query).getByText("gpt-6.1-sol")).toBeInTheDocument();
  });

  it("leaves a turn saved before usage was kept without a breakdown", async () => {
    const log = await reopened(null);
    expect(log.partial).toBe(true);
    expect(
      screen.queryByRole("table", { name: "Cost by operation" }),
    ).toBeNull();
    expect(
      screen.getByText("This run reported what it did, but not what it took."),
    ).toBeInTheDocument();
  });
});
