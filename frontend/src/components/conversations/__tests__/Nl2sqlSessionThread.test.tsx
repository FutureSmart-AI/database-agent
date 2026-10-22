import type { ReactNode } from "react";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/platform/components/ToastContext";

/**
 * A stored conversation, reopened.
 *
 * The excluded-table gate (benchmark TC60) has to hold on this path too: a
 * thread read back from the service carries the same `tables_used`, and a
 * reader opening yesterday's answer would otherwise see the query and rows the
 * live turn withheld.
 */

const ANSWER = {
  role: "assistant",
  chat_id: "chat-1",
  message: "There are 4 return requests pending review.",
  data: {
    nl2sql: {
      sql_query: "SELECT count(*) FROM returns WHERE status = 'requested'",
      tables_used: ["public.returns"],
      db_result: { columns: ["count"], rows: [{ count: 4 }], row_count: 1 },
    },
  },
};

vi.mock("@/platform/components/conversations/nl2sql/FullDatasetModal", () => ({
  default: () => null,
}));
vi.mock("@/platform/components/conversations/ChatFeedbackButtons", () => ({
  default: () => <div data-testid="feedback" />,
}));
vi.mock("@/platform/components/conversations/copy-to-clipboard", () => ({
  CopyToClipboard: () => <button type="button">Copy</button>,
}));
vi.mock("@/platform/hooks/useChatStream", () => ({
  useChatStream: () => ({
    loading: false,
    fetchSessionDetails: vi.fn(async () => []),
    callStreamAnswer: vi.fn(),
    addMessage: vi.fn(),
    resetChat: vi.fn(),
    sessionMessages: [
      { role: "user", message: "how many returns are pending?" },
      ANSWER,
    ],
    chatId: "chat-1",
    error: null,
  }),
}));

const { default: Nl2sqlSessionThread } = await import("../Nl2sqlSessionThread");

const wrap = (node: ReactNode) => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>{node}</ToastProvider>
    </QueryClientProvider>,
  );
};

const renderThread = (excludedTables?: string[]) =>
  wrap(
    <Nl2sqlSessionThread
      sessionId="s-1"
      activeTab="dashboard"
      showSources
      showQuery
      showResults
      rawEnabled={false}
      excludedTables={excludedTables}
    />,
  );

describe("Nl2sqlSessionThread", () => {
  it("withholds a stored answer's query and rows for an excluded table", async () => {
    renderThread(["returns"]);
    // The turn only renders once the session read settles.
    expect(await screen.findByRole("status")).toHaveTextContent(/exclude/i);
    expect(
      screen.queryByRole("tab", { name: "Query" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("cell", { name: "4" })).not.toBeInTheDocument();
    // The answer text itself is still there to read.
    expect(
      screen.getByText(/4 return requests pending review/),
    ).toBeInTheDocument();
  });

  it("shows them when the table is included", async () => {
    renderThread([]);
    expect(
      await screen.findByRole("tab", { name: "Query" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "4" })).toBeInTheDocument();
  });
});
