import type React from "react";

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/platform/components/ToastContext";

import Thread from "../Thread";

vi.mock("@/platform/components/conversations/nl2sql/FullDatasetModal", () => ({
  default: () => null,
}));
vi.mock("@/platform/components/conversations/ChatFeedbackButtons", () => ({
  default: () => <div data-testid="feedback" />,
}));
vi.mock("@/platform/components/conversations/copy-to-clipboard", () => ({
  CopyToClipboard: () => <button type="button">Copy</button>,
}));

/**
 * An assistant message shaped exactly as `useChatStream` hands one over: the
 * session endpoint's `debug_info.nl2sql` and `chart_output.nl2sql` merged back
 * into the live `data.nl2sql` block.
 */
const ANSWER = {
  role: "assistant",
  chat_id: "chat-1",
  response: "There are 93 orders in total.",
  debug_info: {
    refine_query: "count every row in orders",
    latency_ms: 1240,
  },
  data: {
    nl2sql: {
      sql_query: "SELECT count(*) FROM orders",
      tables_used: ["orders"],
      execution_time_ms: 1240,
      db_result: {
        columns: ["total"],
        rows: [{ total: 93 }],
        row_count: 1,
      },
      chart_suggestion: "bar chart",
      chart_data: { data: [{ x: "orders", y: 93 }] },
    },
  },
};

const MESSAGES = [
  { role: "user", message: "how many orders are there?", chat_id: "chat-1" },
  ANSWER,
];

const renderThread = (
  props: Partial<React.ComponentProps<typeof Thread>> = {},
) =>
  render(
    <ToastProvider>
      <Thread
        messages={MESSAGES}
        loading={false}
        streaming={false}
        sessionId="s1"
        chatId="chat-1"
        activeTab="dashboard"
        showSources
        showQuery
        showResults
        rawEnabled={false}
        onPickQuestion={() => {}}
        {...props}
      />
    </ToastProvider>,
  );

describe("Thread", () => {
  it("shows the question and the answer", () => {
    renderThread();
    expect(screen.getByText("how many orders are there?")).toBeInTheDocument();
    expect(screen.getByText(/93 orders in total/)).toBeInTheDocument();
  });

  it("marks the question with the reader's own avatar", () => {
    renderThread();
    expect(screen.getByTestId("asker-avatar")).toBeInTheDocument();
  });

  it("reports one completed trace row per fact the run produced", () => {
    renderThread();
    expect(screen.getByText("Generated SQL")).toBeInTheDocument();
    expect(screen.getByText("SELECT count(*) FROM orders")).toBeInTheDocument();
    expect(screen.getByText("Read table")).toBeInTheDocument();
    expect(screen.getByText("Executed")).toBeInTheDocument();
    // Twice: the trace's timing, and the folded run log's own summary.
    expect(screen.getAllByText("1.24s")).toHaveLength(2);
    expect(screen.getByText("Returned 1 row")).toBeInTheDocument();
  });

  it("renders the result card with the rows the query returned", () => {
    renderThread();
    // The answer carried a chart, so the card opens on it; the rows are a tab
    // away rather than a card away.
    fireEvent.click(screen.getByRole("tab", { name: "Data" }));
    expect(
      screen.getByRole("columnheader", { name: /total/ }),
    ).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "93" })).toBeInTheDocument();
    expect(screen.getByText("1 rows")).toBeInTheDocument();
  });

  it("puts the chart, the rows, the query and the payload in one card", () => {
    renderThread({ rawEnabled: true });
    for (const label of ["Chart", "Data", "Query", "Raw"]) {
      expect(screen.getByRole("tab", { name: label })).toBeInTheDocument();
    }
    fireEvent.click(screen.getByRole("tab", { name: "Query" }));
    // Twice over: the trace's one-line summary, and the highlighted query.
    expect(screen.getAllByText(/SELECT/).length).toBeGreaterThan(1);
  });

  it("logs what the run did in the background", () => {
    renderThread();
    const logs = screen.getByRole("button", { name: /Full logs/ });
    expect(logs).toBeInTheDocument();
    fireEvent.click(logs);
    // This turn reports only the rewritten wording, not the original.
    expect(screen.getByText("Read the question")).toBeInTheDocument();
    expect(screen.getByText("Wrote the query")).toBeInTheDocument();
    expect(screen.getByText("Ran the query")).toBeInTheDocument();
  });

  /**
   * Benchmark TC60: `returns` was marked Excluded in Settings, the agent
   * answered "the requested data source is restricted or not available", and
   * the screen drew the generated SQL and the rows underneath that sentence.
   * Whatever the service does about querying it, this screen does not show the
   * query or the rows for a table the agent is configured to exclude.
   */
  it("withholds the query and rows of a table the agent excludes", () => {
    renderThread({ excludedTables: ["orders"] });
    expect(
      screen.queryByRole("tab", { name: "Query" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Data" })).not.toBeInTheDocument();
    expect(screen.queryByRole("cell", { name: "93" })).not.toBeInTheDocument();
    // The notice names the table and says why its query is not on screen.
    const notice = screen.getByRole("status");
    expect(notice).toHaveTextContent("orders");
    expect(notice).toHaveTextContent(/exclude/i);
    // The answer itself still stands — only its query and rows are withheld.
    expect(screen.getByText(/93 orders in total/)).toBeInTheDocument();
  });

  /**
   * Settings hid the SQL from the card but not from the strip above it, which
   * printed the first sixty characters of the query under every answer.
   */
  it("keeps the query out of the trace and the log when it may not be shown", () => {
    renderThread({ showQuery: false });
    expect(screen.queryByText("Generated SQL")).not.toBeInTheDocument();
    expect(
      screen.queryByText("SELECT count(*) FROM orders"),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Full logs/ }));
    expect(screen.getByText("Wrote the query")).toBeInTheDocument();
    expect(screen.getByText(/does not expose its SQL/)).toBeInTheDocument();
    expect(screen.queryByText(/SELECT count/)).not.toBeInTheDocument();
  });

  it("names no database or table when the agent shows no sources", () => {
    renderThread({ showQuery: false, showResults: false });
    fireEvent.click(screen.getByRole("button", { name: /Full logs/ }));
    expect(screen.queryByText("Selected tables")).not.toBeInTheDocument();
    expect(screen.queryByText("Read tables")).not.toBeInTheDocument();
    expect(screen.queryByText("Chose the database")).not.toBeInTheDocument();
    // The run is still accounted for.
    expect(screen.getByText("Read the question")).toBeInTheDocument();
  });

  it("shows the query and rows when every table read is included", () => {
    renderThread({ excludedTables: ["returns"] });
    expect(screen.getByRole("tab", { name: "Query" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Data" }));
    expect(screen.getByRole("cell", { name: "93" })).toBeInTheDocument();
  });

  it("shows a live trace while the answer is still streaming", () => {
    renderThread({
      streaming: true,
      messages: [
        MESSAGES[0],
        { role: "assistant", response: "There are", chat_id: "chat-1" },
      ],
    });
    expect(screen.getByText("Thinking")).toBeInTheDocument();
    expect(screen.getByText("Writing the answer")).toBeInTheDocument();
  });

  it("hides the SQL and rows when the agent does not show sources", () => {
    renderThread({ showSources: false });
    expect(screen.queryByText("Generated SQL")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("tab", { name: "Query" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/93 orders in total/)).toBeInTheDocument();
  });

  it("surfaces a run failure in place of the answer's trace", () => {
    renderThread({
      error: "The agent could not reach the database.",
      messages: [
        MESSAGES[0],
        { role: "assistant", response: "", chat_id: "c" },
      ],
    });
    expect(
      screen.getAllByText("The agent could not reach the database.").length,
    ).toBeGreaterThan(0);
  });

  it("offers the follow-ups the answer suggested", () => {
    renderThread({
      messages: [
        MESSAGES[0],
        { ...ANSWER, follow_up: ["Which month had the most?"] },
      ],
    });
    expect(
      screen.getByRole("button", { name: "Which month had the most?" }),
    ).toBeInTheDocument();
  });

  it("falls back to the starter questions on an empty thread", () => {
    renderThread({
      messages: [],
      initialSuggestedQuestions: ["What is in this database?"],
    });
    // No turns yet, so the chips belong to the empty state rather than here.
    expect(
      screen.queryByRole("button", { name: "What is in this database?" }),
    ).not.toBeInTheDocument();
  });
});
