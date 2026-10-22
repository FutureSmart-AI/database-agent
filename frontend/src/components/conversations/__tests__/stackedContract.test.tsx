import React from "react";

import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { fetchNl2sqlSession, nl2sqlChatTransport } from "@/data/nl2sqlChat";
import { normalizeNl2sql } from "@/platform/components/conversations/nl2sql/normalizeNl2sql";
import axios from "@/platform/utils/axios";

import { normalizeResultChart } from "../normalizeResultChart";
import ResultCard from "../ResultCard";
import StackedResultChart from "../StackedResultChart";
import root from "./fixtures/root-stacked-installation.json";

vi.mock("@/platform/utils/axios", () => ({ default: { get: vi.fn() } }));
vi.mock("@/platform/components/conversations/nl2sql/FullDatasetModal", () => ({
  default: () => null,
}));
// Supply jsdom's missing element size; actual Recharts geometry still renders.
vi.mock("recharts", async (original) => ({
  ...(await original<typeof import("recharts")>()),
  ResponsiveContainer: ({ children }: { children: React.ReactElement }) => (
    <div>
      {React.cloneElement(children, { width: 800, height: 280 } as object)}
    </div>
  ),
}));

const chart = {
  chart_suggestion: root.chart.suggestion,
  chart_data: { data: root.chart.data, metadata: root.chart.metadata },
};
const debug = {
  sql_query: root.sql,
  db_result: root.db_result,
  selected_tables: ["orders"],
};
const show = (message: unknown) => {
  const view = normalizeNl2sql(message);
  if (!view) throw new Error("Missing normalized result");
  render(<ResultCard view={view} raw={message} showQuery rawEnabled />);
  return view;
};

describe("stacked chart through product transport and result card", () => {
  it("renders the root live response without changing SQL/rows or flattening series", () => {
    const response = {
      response: root.answer,
      debug_info: debug,
      chart_output: chart,
    };
    const original = JSON.stringify(response);
    const event = nl2sqlChatTransport("NL2SQL_TEST")!.adaptEvent!(response);
    const view = show(event);
    expect(
      screen.getByRole("tab", { name: "Chart", selected: true }),
    ).toBeInTheDocument();
    const table = screen.getByRole("table", {
      name: /original segment values/,
    });
    expect(
      within(table).getByRole("columnheader", { name: "North" }),
    ).toBeInTheDocument();
    expect(
      within(table).getByRole("columnheader", { name: "South" }),
    ).toBeInTheDocument();
    expect(within(table).getByText("250")).toBeInTheDocument();
    expect(within(table).getByText("200")).toBeInTheDocument();
    expect(
      screen.queryByRole("group", { name: "Chart type" }),
    ).not.toBeInTheDocument();
    expect(document.querySelectorAll(".recharts-bar")).toHaveLength(2);
    expect(view.sqlQuery).toBe(root.sql);
    expect(JSON.stringify(response)).toBe(original);
    fireEvent.click(screen.getByRole("tab", { name: "Data" }));
    expect(
      screen.getByRole("cell", { name: /^250$/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("cell", { name: /^200$/ }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Query" }));
    expect(screen.getByText(/SUM/)).toBeInTheDocument();
  });

  it("reopens the identical saved chart through the real stored-session adapter", async () => {
    vi.mocked(axios.get).mockResolvedValueOnce({
      data: {
        conversation_data: [
          {
            role: "assistant",
            message: root.answer,
            debug_info: debug,
            graph_output: chart,
          },
        ],
      },
    });
    const session = await fetchNl2sqlSession("NL2SQL_TEST", "saved-session");
    const wire = session.conversation_data[0] as {
      debug_info: string;
      chart_output: string;
    };
    const savedDebug = JSON.parse(wire.debug_info);
    const message = {
      debug_info: savedDebug,
      chart_output: JSON.parse(wire.chart_output),
      data: { nl2sql: savedDebug.nl2sql },
    };
    const view = show(message);
    expect(view.chart).toEqual(root.chart);
    expect(view.sqlQuery).toBe(root.sql);
    expect(
      screen.getByRole("tab", { name: "Chart", selected: true }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("table", { name: /original segment values/ }),
    ).toBeInTheDocument();
  });

  it("keeps Data/Query/Raw when a malformed stacked chart has an explicit error", () => {
    show({
      debug_info: debug,
      chart_output: {
        ...chart,
        chart_data: {
          data: [
            { index: "Invalid", segments: [{ category: "Bad", value: null }] },
          ],
        },
      },
    });
    expect(screen.getByRole("status")).toHaveTextContent(
      "finite numeric value",
    );
    expect(screen.getByRole("tab", { name: "Data" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Query" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Raw" })).toBeInTheDocument();
  });

  it("draws unseen signed/sparse series while retaining every raw value and missing cell", () => {
    const normalized = normalizeResultChart({
      suggestion: "Stacked Bar Chart",
      data: [
        {
          index: "Period P",
          segments: [
            { category: "Income", value: 31.5 },
            { category: "Cost", value: -6.5 },
            { category: "Adjustment", value: 0 },
          ],
        },
        {
          index: "Period Q",
          segments: [
            { category: "Income", value: 0 },
            { category: "Extra", value: 9 },
          ],
        },
      ],
    });
    if (normalized?.shape !== "stacked")
      throw new Error("Expected stacked chart");
    render(
      <StackedResultChart
        chart={normalized.chart}
        title="Held-out signed values"
      />,
    );
    expect(document.querySelectorAll(".recharts-bar")).toHaveLength(4);
    const table = screen.getByRole("table", {
      name: /original segment values/,
    });
    expect(within(table).getByText("31.5")).toBeInTheDocument();
    expect(within(table).getByText("-6.5")).toBeInTheDocument();
    expect(within(table).getAllByText("0")).toHaveLength(2);
    expect(within(table).getAllByText("Not provided")).toHaveLength(3);
    expect(
      within(table).getByRole("columnheader", { name: "Extra" }),
    ).toBeInTheDocument();
  });

  it("draws percentage axes with unchanged original segment values", () => {
    const normalized = normalizeResultChart({
      suggestion: "Stacked Bar Chart",
      data: [
        {
          index: "Sample",
          segments: [
            { category: "Small", value: 1 },
            { category: "Large", value: 3 },
          ],
        },
      ],
      metadata: { stack_type: "percent", chart_orientation: "vertical" },
    });
    if (normalized?.shape !== "stacked")
      throw new Error("Expected percent chart");
    render(
      <StackedResultChart
        chart={normalized.chart}
        title="Held-out composition"
      />,
    );
    expect(screen.getByText("100%")).toBeInTheDocument();
    expect(
      screen.getByText(/tooltips show the original values/),
    ).toBeInTheDocument();
    const table = screen.getByRole("table", {
      name: /original segment values/,
    });
    expect(within(table).getByText("1")).toBeInTheDocument();
    expect(within(table).getByText("3")).toBeInTheDocument();
    expect(document.querySelectorAll(".recharts-bar")).toHaveLength(2);
  });
});
