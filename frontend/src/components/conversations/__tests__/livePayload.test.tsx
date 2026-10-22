import type React from "react";

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/platform/components/ToastContext";

import { nl2sqlChatTransport } from "../../../data/nl2sqlChat";
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
 * One real answer off the deployed service, field for field.
 *
 * Captured from `POST /nl2sql/api/v1/agents/{id}/chat` on 2026-09-22. It is
 * kept verbatim — including `graph_output`, which mirrors `chart_output` — so
 * this file answers one question: does every field the service sends reach the
 * screen? Anything trimmed here would be a field the test stops watching.
 */
const PAYLOAD = {
  response:
    "## Missing Logs Report – Last Week (Active Members)\n\nThe query counted the number of days **without a work-log entry** for each active user.\n\n| Member Name | Days Missing Logs |\n|-------------|-------------------|\n| Arijeet Nandy | **5** |\n| Shreyas | **4** |\n",
  session_id: "74ae7fd5-b513-4f50-ac17-9dc7ee53fc45",
  chat_id: "4c0eed8b-8735-4c70-8628-1f4dbc338eb8",
  follow_up: [
    "Which active members missed logs on all 5 days?",
    "How many active members had fewer than 5 missing log days?",
  ],
  is_answered: true,
  trace_id: "01a0c860-ff83-7523-9a63-c466e184016b",
  debug_info: {
    query: "give me report for last week missing logs for each active member",
    refined_query:
      "Give a report for last week of missing logs for each active member.",
    selected_db_id: "DB_D554AD63",
    selected_db_name: "prod_db",
    sql_query:
      "SELECT u.id, u.name, COUNT(DISTINCT d.date) FILTER (WHERE wl.id IS NULL) AS missing_logs_count FROM users u JOIN user_status us ON u.id = us.user_id AND us.status = 'active' LEFT JOIN work_logs wl ON u.id = wl.user_id GROUP BY u.id, u.name ORDER BY missing_logs_count DESC LIMIT 10;",
    selected_tables: ["users", "work_logs", "user_status"],
    db_result: {
      columns: [
        { name: "id", type: "string" },
        { name: "name", type: "string" },
        { name: "missing_logs_count", type: "integer" },
      ],
      rows: [
        {
          id: "f78e819e-0e36-478e-abbf-6162ff8765dc",
          name: "Arijeet Nandy",
          missing_logs_count: 5,
        },
        {
          id: "24480cf9-6db9-471b-97ee-a1288cffceef",
          name: "Shreyas",
          missing_logs_count: 4,
        },
      ],
      row_count: 2,
      truncated: false,
    },
  },
  chart_output: {
    chart_suggestion: "Bar Chart",
    chart_data: {
      data: [
        { category: "Arijeet Nandy", value: 5 },
        { category: "Shreyas", value: 4 },
      ],
      metadata: {
        title: "Missing Logs for Active Members (Last Week)",
        x_axis: { label: "Member Name", field: "name" },
        y_axis: { label: "Missing Log Count", field: "missing_logs_count" },
        legend: { show: false, position: "right" },
        colors: ["#4facfe", "#00f2fe"],
      },
    },
    metadata: null,
  },
  graph_output: {
    chart_suggestion: "Bar Chart",
    chart_data: { data: [{ category: "Arijeet Nandy", value: 5 }] },
  },
};

/**
 * The assistant message as `useChatStream` assembles one: the transport's
 * adapted event, plus the fields the hook copies onto the turn.
 */
const answerFromPayload = (payload: Record<string, unknown>) => {
  const transport = nl2sqlChatTransport("NL2SQL_TEST")!;
  const event = transport.adaptEvent!(payload) as Record<string, unknown>;
  return {
    role: "assistant",
    chat_id: event.chat_id,
    response: event.response,
    debug_info: event.debug_info,
    follow_up: event.follow_up,
    trace_id: event.trace_id,
    is_answered: event.is_answered,
    data: event.data,
  };
};

const renderPayload = (
  payload: Record<string, unknown> = PAYLOAD,
  props: Partial<React.ComponentProps<typeof Thread>> = {},
) =>
  render(
    <ToastProvider>
      <Thread
        messages={[
          {
            role: "user",
            message: "give me report for last week missing logs",
            chat_id: "4c0eed8b",
          },
          answerFromPayload(payload),
        ]}
        loading={false}
        streaming={false}
        sessionId="74ae7fd5"
        chatId="4c0eed8b"
        activeTab="dashboard"
        showSources
        showQuery
        showResults
        rawEnabled
        onPickQuestion={() => {}}
        {...props}
      />
    </ToastProvider>,
  );

describe("a live NL2SQL answer, field by field", () => {
  it("renders the answer and the follow-up questions", () => {
    renderPayload();
    expect(screen.getByText(/Missing Logs Report/)).toBeInTheDocument();
    for (const question of PAYLOAD.follow_up) {
      expect(screen.getByText(question)).toBeInTheDocument();
    }
  });

  it("shows the query and the tables it read", () => {
    renderPayload();
    fireEvent.click(screen.getByRole("tab", { name: "Query" }));
    expect(screen.getAllByText(/work_logs/).length).toBeGreaterThan(0);
    const logs = screen.getByRole("button", { name: /Full logs/ });
    fireEvent.click(logs);
    expect(screen.getByText("Selected tables")).toBeInTheDocument();
    expect(
      screen.getByText(/3 tables · users, work_logs, user_status/),
    ).toBeInTheDocument();
  });

  it("draws the rows in the order and with the types the service declared", () => {
    renderPayload();
    fireEvent.click(screen.getByRole("tab", { name: "Data" }));
    const headers = screen
      .getAllByRole("columnheader")
      .map((cell) => cell.textContent);
    // `id` is folded away by default, so the declared order shows as name first.
    expect(headers[0]).toContain("name");
    expect(headers[1]).toContain("missing_logs_count");
    // The declared type is on the header, not guessed from the values.
    expect(headers[1]).toContain("integer");
    expect(headers[0]).toContain("string");
    expect(screen.getByRole("cell", { name: "Arijeet Nandy" })).toBeVisible();
    expect(screen.getAllByRole("cell", { name: "5" }).length).toBe(1);
  });

  it("titles the chart the way the run titled it", () => {
    renderPayload();
    expect(
      screen.getByText("Missing Logs for Active Members (Last Week)"),
    ).toBeInTheDocument();
    // The suggestion is still reported — as the chart's type, not its title.
    expect(screen.getByText(/Suggested chart:/)).toBeInTheDocument();
    expect(screen.getByText(/Member Name/)).toBeInTheDocument();
    expect(screen.getByText(/Missing Log Count/)).toBeInTheDocument();
  });

  it("logs the rewritten question, the database and the trace id", () => {
    renderPayload();
    fireEvent.click(screen.getByRole("button", { name: /Full logs/ }));
    expect(screen.getByText("Rewrote the question")).toBeInTheDocument();
    expect(screen.getByText("Chose the database")).toBeInTheDocument();
    expect(screen.getByText("prod_db")).toBeInTheDocument();
    expect(screen.getByText(`trace ${PAYLOAD.trace_id}`)).toBeInTheDocument();
  });

  it("flags a turn the service says it did not answer", () => {
    renderPayload({ ...PAYLOAD, is_answered: false });
    fireEvent.click(screen.getByRole("button", { name: /Full logs/ }));
    expect(screen.getByText("Reported no answer")).toBeInTheDocument();
  });

  it("still draws the chart when only graph_output carries it", () => {
    const { chart_output: _dropped, ...withoutChartOutput } = PAYLOAD;
    renderPayload(withoutChartOutput);
    expect(screen.getByRole("tab", { name: "Chart" })).toBeInTheDocument();
    expect(screen.getByText(/Suggested chart:/)).toBeInTheDocument();
    // The run log reports the chart step off the same block.
    fireEvent.click(screen.getByRole("button", { name: /Full logs/ }));
    expect(screen.getByText("Built a Bar Chart")).toBeInTheDocument();
  });

  it("dumps the untouched payload under Raw", () => {
    renderPayload();
    fireEvent.click(screen.getByRole("tab", { name: "Raw" }));
    expect(screen.getByText(/DB_D554AD63/)).toBeInTheDocument();
  });
});
