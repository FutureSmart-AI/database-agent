import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AxiosError, AxiosHeaders } from "axios";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { SessionRow, Turn } from "@/data/conversations";
import type { ActivityRow } from "@/data/shareActivity";

/**
 * Share → Activity: what other people asked, read-only.
 *
 * Both stores are mocked. What is under test is the screen's own work: that the
 * list is built from the query log (the session list answers `{"sessions": []}`
 * for agents that plainly have conversations), that a session the service DOES
 * list is merged in rather than duplicated, the filters, the two empty states,
 * and that opening a row gives a conversation with no way to answer it.
 */

const logged = (over: Partial<ActivityRow> = {}): ActivityRow => ({
  id: "s1",
  sessionId: "s1",
  who: "analyst@acme-retail.com",
  fromWidget: false,
  title: "Top 5 customers by total spend",
  asked: 3,
  at: Date.now() - 2 * 864e5,
  latency: 1840,
  ...over,
});

const activityRows: ActivityRow[] = [
  logged(),
  logged({
    id: "s2",
    sessionId: "s2",
    who: "ops.lead@acme-retail.com",
    title: "Which payment methods bring in the most revenue?",
    asked: 1,
    at: Date.now() - 40 * 864e5,
  }),
  logged({
    id: "w1",
    sessionId: "w1",
    who: null,
    fromWidget: true,
    title: "Do you ship to Canada?",
    asked: 2,
    at: Date.now() - 3600e3,
  }),
];

const sessionRow = (over: Partial<SessionRow> = {}): SessionRow => ({
  session_id: "s9",
  agent_id: "AG_1",
  user_id: "pradip@futuresmart.ai",
  session_title: "Give me the order status details",
  display_message: "Give me the order status details",
  from_chat_widget: false,
  created_time: new Date(Date.now() - 5 * 864e5).toISOString(),
  ...over,
});

const turnRows: Turn[] = [
  {
    chat_id: "c1",
    question: "Top 5 customers by total spend",
    answer: "Here are the five highest-spending customers.",
    timestamp: new Date().toISOString(),
    feedback: null,
    latency: 1840,
    sql: "SELECT customer_id FROM orders",
    tables: ["orders"],
    chart: null,
  } as Turn,
];

const useSessions = vi.fn();
const useSessionTurns = vi.fn();
const useActivityQueries = vi.fn();

vi.mock("@/data/conversations", () => ({
  useSessions: (agentId: string | undefined, source: string) =>
    useSessions(agentId, source),
  useSessionTurns: (agentId: string | undefined, sessionId: string | null) =>
    useSessionTurns(agentId, sessionId),
}));
vi.mock("@/data/shareActivity", () => ({
  useActivityQueries: (
    agentId: string | undefined,
    window: { days: number | null },
  ) => useActivityQueries(agentId, window),
}));

const { default: ShareActivity } = await import("../ShareActivity");

beforeEach(() => {
  vi.clearAllMocks();
  useActivityQueries.mockReturnValue({
    data: { rows: activityRows, truncated: false },
    isLoading: false,
    isError: false,
    error: null,
  });
  useSessions.mockReturnValue({ data: [], isLoading: false, error: null });
  useSessionTurns.mockReturnValue({
    data: turnRows,
    isLoading: false,
    error: null,
  });
});

const rows = () => screen.getAllByRole("row").slice(1);

describe("Share → Activity", () => {
  it("builds the list from the query log, split by where the question came from", () => {
    render(<ShareActivity agentId="AG_1" />);
    expect(useActivityQueries).toHaveBeenCalledWith("AG_1", { days: null });
    const tabs = screen.getByRole("tablist", { name: "Activity source" });
    expect(
      within(tabs).getByRole("tab", { name: /shared users/i }),
    ).toHaveAttribute("aria-selected", "true");
    // Two signed-in conversations, one from the bubble.
    expect(within(tabs).getByText("2")).toBeInTheDocument();
    expect(within(tabs).getByText("1")).toBeInTheDocument();
    expect(rows()).toHaveLength(2);
    // The log knows how many questions each conversation carried.
    expect(
      screen.getByRole("columnheader", { name: /questions asked/i }),
    ).toBeInTheDocument();
    expect(rows()[0]).toHaveTextContent("3");
  });

  it("switches to the bubble's own conversations", async () => {
    render(<ShareActivity agentId="AG_1" />);
    await userEvent.click(screen.getByRole("tab", { name: /widget/i }));
    expect(screen.getByText("Do you ship to Canada?")).toBeInTheDocument();
    expect(rows()).toHaveLength(1);
    // A bubble question has no signed-in asker, so the column says which it is.
    expect(screen.getByText("Website visitor")).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: /visitor/i }),
    ).toBeInTheDocument();
  });

  it("merges a session the service does list, without duplicating it", () => {
    useSessions.mockImplementation((_id: string, source: string) => ({
      data:
        source === "users"
          ? [sessionRow(), sessionRow({ session_id: "s1" })]
          : [],
      isLoading: false,
      error: null,
    }));
    render(<ShareActivity agentId="AG_1" />);
    // s9 is new; s1 is already in the log and must not appear twice.
    expect(rows()).toHaveLength(3);
    expect(
      screen.getByText("Give me the order status details"),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Top 5 customers by total spend")).toHaveLength(
      1,
    );
  });

  it("re-reads the log when the date range changes", async () => {
    render(<ShareActivity agentId="AG_1" />);
    await userEvent.selectOptions(screen.getByLabelText("Date range"), "7");
    await waitFor(() =>
      expect(useActivityQueries).toHaveBeenCalledWith("AG_1", { days: 7 }),
    );
    await waitFor(() => expect(rows()).toHaveLength(1));
  });

  it("filters by search and says how much of the list is showing", async () => {
    render(<ShareActivity agentId="AG_1" />);
    expect(screen.getByText("2 of 2 shown")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Search activity"), "payment");
    await waitFor(() => expect(rows()).toHaveLength(1));
    expect(screen.getByText("1 of 2 shown")).toBeInTheDocument();
  });

  it("offers a way out of a filter that matches nothing", async () => {
    render(<ShareActivity agentId="AG_1" />);
    await userEvent.type(screen.getByLabelText("Search activity"), "zzzz");
    await waitFor(() =>
      expect(
        screen.getByText("Nothing matches your filters"),
      ).toBeInTheDocument(),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Clear filters" }),
    );
    expect(rows()).toHaveLength(2);
  });

  it("tells an empty store apart from an empty filter", () => {
    useActivityQueries.mockReturnValue({
      data: { rows: [], truncated: false },
      isLoading: false,
      isError: false,
      error: null,
    });
    render(<ShareActivity agentId="AG_1" />);
    expect(screen.getByText("Nothing shared yet")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Clear filters" })).toBeNull();
  });

  it("lists a session the service left `from_chat_widget` off", () => {
    // The service omits the flag on a shared-user session, so the field arrives
    // undefined however the type spells it. The tab counted such a row (`!undefined`)
    // while the list dropped it (`undefined === false`), which read as
    // "Nothing shared yet" under a tab badge saying 6.
    useActivityQueries.mockReturnValue({
      data: { rows: [], truncated: false },
      isLoading: false,
      isError: false,
      error: null,
    });
    useSessions.mockImplementation((_agentId: string, source: string) => ({
      data:
        source === "users"
          ? [
              sessionRow({
                from_chat_widget: undefined as unknown as boolean,
              }),
            ]
          : [],
      isLoading: false,
      error: null,
    }));
    render(<ShareActivity agentId="AG_1" />);
    const tabs = screen.getByRole("tablist", { name: "Activity source" });
    expect(within(tabs).getByText("1")).toBeInTheDocument();
    expect(screen.queryByText("Nothing shared yet")).toBeNull();
    expect(rows()).toHaveLength(1);
    expect(
      screen.getByText("Give me the order status details"),
    ).toBeInTheDocument();
  });

  it("treats a brand-new agent's 404 as an empty log, not a failure", () => {
    useActivityQueries.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      error: { response: { status: 404 } },
    });
    render(<ShareActivity agentId="AG_1" />);
    expect(screen.getByText("Nothing shared yet")).toBeInTheDocument();
  });

  it("reports a real failure of the log", () => {
    // `apiMessage` only trusts a real Axios error, so the fixture is one.
    const failure = new AxiosError("Request failed", "500", undefined, null, {
      status: 500,
      data: { detail: "boom" },
      statusText: "Internal Server Error",
      headers: {},
      config: { headers: new AxiosHeaders() },
    });
    useActivityQueries.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      error: failure,
    });
    render(<ShareActivity agentId="AG_1" />);
    expect(screen.getByText(/boom/i)).toBeInTheDocument();
  });

  it("says when the log had more than it returned", () => {
    useActivityQueries.mockReturnValue({
      data: { rows: activityRows, truncated: true },
      isLoading: false,
      isError: false,
      error: null,
    });
    render(<ShareActivity agentId="AG_1" />);
    expect(
      screen.getByText(/showing the most recent 100 questions/i),
    ).toBeInTheDocument();
  });

  it("sorts by whichever column is asked for", async () => {
    render(<ShareActivity agentId="AG_1" />);
    expect(rows()[0]).toHaveTextContent("Top 5 customers");
    await userEvent.click(
      screen.getByRole("button", { name: /^last activity/i }),
    );
    expect(rows()[0]).toHaveTextContent("Which payment methods");
    // A numeric column opens on its largest value: three questions beats one.
    await userEvent.click(
      screen.getByRole("button", { name: /^questions asked/i }),
    );
    expect(rows()[0]).toHaveTextContent("Top 5 customers");
    await userEvent.click(
      screen.getByRole("button", { name: /^questions asked/i }),
    );
    expect(rows()[0]).toHaveTextContent("Which payment methods");
  });

  it("opens a conversation read-only, with no way to answer it", async () => {
    render(<ShareActivity agentId="AG_1" />);
    await userEvent.click(screen.getByText("Top 5 customers by total spend"));
    expect(useSessionTurns).toHaveBeenCalledWith("AG_1", "s1");
    expect(
      screen.getByText(/here are the five highest-spending customers/i),
    ).toBeInTheDocument();
    expect(screen.getByText("Executed SQL")).toBeInTheDocument();
    expect(screen.getByText(/read-only/i)).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: /back/i }));
    expect(rows()).toHaveLength(2);
  });

  /**
   * Benchmark TC58: an operator could find and open the exchange someone
   * complained about, but not see *why* the answer was wrong — the panel that
   * would carry the query simply was not there. A turn keeps no SQL when the
   * agent recorded no diagnostics, so the viewer says that rather than leaving
   * an operator to wonder whether the query is missing or hidden.
   */
  it("says so when a turn recorded no query, instead of showing nothing", async () => {
    useSessionTurns.mockReturnValue({
      data: [{ ...turnRows[0], sql: null, tables: [], latency: null } as Turn],
      isLoading: false,
      error: null,
    });
    render(<ShareActivity agentId="AG_1" />);
    await userEvent.click(screen.getByText("Top 5 customers by total spend"));
    expect(screen.queryByText("Executed SQL")).toBeNull();
    expect(screen.getByText(/no query was recorded/i)).toBeInTheDocument();
    expect(screen.getByText(/show sources/i)).toBeInTheDocument();
    // The answer it did give is still readable.
    expect(
      screen.getByText(/here are the five highest-spending customers/i),
    ).toBeInTheDocument();
  });

  it("leaves a logged question with no thread listed but not clickable", async () => {
    useActivityQueries.mockReturnValue({
      data: {
        rows: [logged({ id: "c9", sessionId: null, asked: 1 })],
        truncated: false,
      },
      isLoading: false,
      isError: false,
      error: null,
    });
    render(<ShareActivity agentId="AG_1" />);
    const row = rows()[0];
    expect(row).toHaveAttribute(
      "title",
      "The service has no thread for this question",
    );
    await userEvent.click(row);
    // Still the list: there is no thread to open.
    expect(screen.getByRole("table")).toBeInTheDocument();
  });

  it("asks for no thread until one is opened", () => {
    render(<ShareActivity agentId="AG_1" />);
    expect(useSessionTurns).toHaveBeenCalledWith("AG_1", null);
  });
});
