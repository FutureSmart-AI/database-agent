import { describe, expect, it } from "vitest";

import { normalizeNl2sql } from "@/platform/components/conversations/nl2sql/normalizeNl2sql";

import { formatCost, formatMs, readRunLog } from "../runLog";

/**
 * A turn as `useChatStream` hands one over: the service's `debug_info` beside
 * the `data.nl2sql` block the transport derives from it.
 */
const SQL = "SELECT count(*)\n  FROM orders\n WHERE status = 'paid'";

const message = (debug: Record<string, unknown> = {}) => ({
  role: "assistant",
  response: "93 orders are paid.",
  debug_info: {
    query: "how many orders are paid?",
    refine_query: "count orders with status paid",
    selected_db_name: "retail",
    selected_db_id: "db-1",
    selected_tables: ["orders"],
    sql_query: SQL,
    db_result: { columns: ["total"], rows: [{ total: 93 }], row_count: 1 },
    latency_ms: 1240,
    ...debug,
  },
  data: {
    nl2sql: {
      sql_query: SQL,
      tables_used: ["orders"],
      db_result: { columns: ["total"], rows: [{ total: 93 }], row_count: 1 },
      execution_time_ms: 1240,
    },
  },
});

const logOf = (raw: unknown, error?: string) =>
  readRunLog({ message: raw, view: normalizeNl2sql(raw), error });

const labels = (raw: unknown, error?: string) =>
  (logOf(raw, error)?.steps ?? []).map((step) => step.label);

describe("readRunLog", () => {
  it("logs the run end to end, in the order it happened", () => {
    expect(labels(message())).toEqual([
      "Rewrote the question",
      "Chose the database",
      "Selected tables",
      "Wrote the query",
      "Ran the query",
    ]);
  });

  it("says the question was only read when it was not rewritten", () => {
    const log = logOf(message({ refine_query: "how many orders are paid?" }));
    expect(log?.steps[0].label).toBe("Read the question");
    // Nothing to unfold: there is no second wording to compare against.
    expect(log?.steps[0].lines).toBeUndefined();
  });

  it("keeps both wordings under the step that rewrote the question", () => {
    const [question] = logOf(message())!.steps;
    expect(question.lines).toEqual([
      "asked:   how many orders are paid?",
      "used:    count orders with status paid",
    ]);
  });

  it("carries the whole query, not just its summary", () => {
    const sql = logOf(message())!.steps.find((step) => step.key === "sql")!;
    expect(sql.detail).toBe(
      "SELECT count(*) FROM orders WHERE status = 'paid'",
    );
    expect(sql.lines).toEqual(SQL.split("\n"));
  });

  it("reports the rows and the time the query took", () => {
    const exec = logOf(message())!.steps.find((step) => step.key === "exec")!;
    expect(exec.detail).toBe("1 row · 1.24s");
  });

  /**
   * The service reports `selected_tables` when it schema-picks; when it does
   * not, the transport reads the tables off the query itself. A log that
   * passed the second off as the first would have an owner chasing a table
   * selection the run never made.
   */
  it("says when the tables were read off the query rather than selected", () => {
    const log = logOf(message({ selected_tables: undefined }));
    const tables = log!.steps.find((step) => step.key === "tables")!;
    expect(tables.label).toBe("Read tables");
    expect(tables.lines?.join(" ")).toMatch(/Read off the generated query/);
  });

  it("logs the steps the run narrated about itself", () => {
    const log = logOf(
      message({ steps: [{ name: "Plan", detail: "chose 1 table" }] }),
    );
    const plan = log!.steps.find((step) => step.label === "Plan")!;
    expect(plan.detail).toBe("chose 1 table");
  });

  it("logs a chart the answer came with, and one it decided against", () => {
    const drew = logOf({
      ...message(),
      data: {
        nl2sql: {
          chart_suggestion: "bar chart",
          chart_data: { data: [{ x: "paid", y: 93 }] },
        },
      },
    });
    expect(drew!.steps.at(-1)!.label).toBe("Built a bar chart");

    const declined = logOf({
      ...message(),
      chart_output: {},
    });
    const chart = declined!.steps.find((step) => step.key === "chart")!;
    expect(chart.label).toBe("Decided against a chart");
    expect(chart.state).toBe("skipped");
  });

  it("ends a failed run with the failure, in red", () => {
    const log = logOf(message(), "The agent could not reach the database.");
    const last = log!.steps.at(-1)!;
    expect(last.state).toBe("failed");
    expect(last.detail).toBe("The agent could not reach the database.");
  });

  /**
   * No deployed turn carries a `usage` block today, so the panel has to say
   * what it has rather than print zero tokens and $0.0000.
   */
  it("marks a turn with no usage block as partial", () => {
    expect(logOf(message())!.partial).toBe(true);
    expect(logOf(message())!.totals?.totalTokens).toBeUndefined();
    expect(logOf(message())!.totals?.latencyMs).toBe(1240);
  });

  it("totals the per-service calls when the run reports them", () => {
    const log = logOf(
      message({
        usage: {
          total_tokens: 1820,
          service_calls: [
            {
              service: "sql_generation",
              latency_ms: 900,
              cost_usd: 0.0021,
              model: "claude-sonnet-5",
            },
            { service: "chart", latency_ms: 340, cost_usd: 0.0004 },
          ],
        },
      }),
    );
    expect(log!.partial).toBe(false);
    expect(log!.totals).toMatchObject({ latencyMs: 1240, totalTokens: 1820 });
    expect(log!.totals!.costUsd).toBeCloseTo(0.0025, 6);
    expect(log!.model).toBe("claude-sonnet-5");
  });

  it("reports nothing for a turn the service said nothing about", () => {
    expect(
      readRunLog({ message: { response: "hello" }, view: null }),
    ).toBeNull();
  });
});

describe("formatting", () => {
  it("reads sub-second timings in milliseconds", () => {
    expect(formatMs(340)).toBe("340ms");
    expect(formatMs(1240)).toBe("1.24s");
  });

  it("does not round a real cost away to zero", () => {
    expect(formatCost(0.00004)).toBe("<$0.0001");
    expect(formatCost(0.0021)).toBe("$0.0021");
  });

  describe("NL2SQL usage block", () => {
    const usage = (overrides: Record<string, unknown> = {}) => ({
      latency_ms: 18450,
      input_tokens: 9100,
      output_tokens: 1200,
      estimated_cost_usd: 0.0213,
      cost_complete: true,
      price_table: "openai-standard-2026-10-25",
      excludes: ["follow_up_suggestions"],
      nodes: [
        {
          node: "router",
          provider: "openai",
          model: "gpt-6-luna",
          input_tokens: 900,
          output_tokens: 40,
          latency_ms: 900,
          estimated_cost_usd: 0.00011,
        },
        {
          node: "select_table",
          provider: "openai",
          model: "gpt-6.1-sol",
          input_tokens: 1500,
          output_tokens: 30,
          latency_ms: 2400,
          estimated_cost_usd: 0.0033,
        },
        {
          node: "sql_gen",
          provider: "openai",
          model: "gpt-6.1-sol",
          input_tokens: 6000,
          output_tokens: 900,
          latency_ms: 12000,
          estimated_cost_usd: 0.021,
        },
        {
          node: "sql_exec",
          latency_ms: 40,
          input_tokens: 0,
          output_tokens: 0,
          estimated_cost_usd: null,
        },
        {
          node: "final_answer",
          provider: "openai",
          model: "gpt-6-luna",
          input_tokens: 2200,
          output_tokens: 260,
          latency_ms: 3100,
          estimated_cost_usd: 0.00035,
        },
      ],
      ...overrides,
    });

    it("takes the run's latency, tokens and estimated cost, and costs each step", () => {
      const log = logOf({ ...message(), usage: usage() });
      expect(log?.totals).toEqual({
        latencyMs: 18450,
        totalTokens: 10300,
        costUsd: 0.0213,
        costEstimated: true,
        costIncomplete: false,
      });
      const sql = log?.steps.find((step) => step.key === "sql");
      expect(sql?.call).toMatchObject({
        model: "gpt-6.1-sol",
        inputTokens: 6000,
        outputTokens: 900,
        costUsd: 0.021,
        estimated: true,
      });
      expect(
        log?.steps.find((step) => step.key === "tables")?.call,
      ).toMatchObject({ model: "gpt-6.1-sol", latencyMs: 2400 });
      const answer = log?.steps.find((step) => step.key === "answer");
      expect(answer?.label).toBe("Wrote the answer");
      expect(answer?.call?.model).toBe("gpt-6-luna");
    });

    it("lists every operation the run paid for, with its model, so the rows add up", () => {
      const extra = {
        node: "other_calls",
        provider: "openai",
        model: "gpt-6-luna",
        input_tokens: 500,
        output_tokens: 20,
        latency_ms: null,
        calls: 2,
        estimated_cost_usd: 0.00006,
      };
      const unknown = {
        node: "rerank",
        model: "gpt-6-luna",
        input_tokens: 10,
        output_tokens: 1,
        estimated_cost_usd: 0.00001,
      };
      const base = usage();
      const log = logOf({
        ...message(),
        usage: {
          ...base,
          nodes: [...(base.nodes as unknown[]), extra, unknown],
        },
      });
      const operations = log?.operations ?? [];
      expect(operations.map((operation) => operation.label)).toEqual([
        "Routed the question",
        "Selected tables",
        "Wrote the query",
        "Ran the query",
        "Wrote the answer",
        "Other model calls",
        "rerank",
      ]);
      expect(operations[0]).toMatchObject({
        model: "gpt-6-luna",
        latencyMs: 900,
        inputTokens: 900,
        outputTokens: 40,
        costUsd: 0.00011,
      });
      expect(operations[3]).toMatchObject({
        model: undefined,
        latencyMs: 40,
        costUsd: undefined,
      });
      expect(operations[5]).toMatchObject({
        model: "gpt-6-luna",
        latencyMs: undefined,
        calls: 2,
      });
    });

    it("reads usage stored with a reloaded turn", () => {
      // A reloaded turn carries `usage` inside `debug_info`, not beside it.
      const log = logOf(message({ usage: usage() }));
      expect(log?.partial).toBe(false);
      expect(log?.totals?.costUsd).toBe(0.0213);
      expect(log?.operations).toHaveLength(5);
    });

    it("withholds a total that would count an unpriced model as free", () => {
      const log = logOf({
        ...message(),
        usage: usage({ cost_complete: false }),
      });
      expect(log?.totals?.costUsd).toBeUndefined();
      expect(log?.totals?.costIncomplete).toBe(true);
      expect(log?.totals?.latencyMs).toBe(18450);
    });

    it("leaves a stored turn without usage as it was", () => {
      const log = logOf(message());
      expect(log?.totals?.costEstimated).toBeUndefined();
      expect(log?.steps.some((step) => step.key === "answer")).toBe(false);
      expect(log?.operations).toBeUndefined();
    });
  });
});
