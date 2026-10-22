import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { normalizeNl2sql } from "@/platform/components/conversations/nl2sql/normalizeNl2sql";
import { useChatStream } from "@/platform/hooks/useChatStream";
import axios from "@/platform/utils/axios";

import { nl2sqlChatTransport } from "../nl2sqlChat";

/**
 * A Database Agent answer, from the wire to the view.
 *
 * The unit tests either side of this one mock the transport or call the hook
 * with a hand-written one. This drives the *real* transport through the real
 * hook with only the network stubbed, because the defect this covers lived in
 * the wiring between them: the live answer carries no `debug_info` — the
 * request deliberately does not ask for it, and the agent default is off — so
 * the turn that had just been answered showed no SQL, no tables and no rows
 * until the reader reloaded the page.
 */

const AGENT = "NL2SQL_76CC79E1";
const SESSION = "sess-live-1";

vi.mock("@/platform/utils/axios", () => ({
  default: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

vi.mock("@/platform/components/ToastContext", () => ({
  useToast: () => ({ toast: { error: vi.fn(), success: vi.fn() } }),
}));

vi.mock("@/platform/hooks/useAuth", () => ({
  useAuth: () => ({ agentId: AGENT, profile: { user_id: "u-1" } }),
}));

const SQL =
  "SELECT c.id, c.name, SUM(o.total_amount) AS total_spend FROM customers c JOIN orders o ON c.id = o.customer_id GROUP BY c.id, c.name ORDER BY total_spend DESC LIMIT 5";

/**
 * What the service actually streams: the answer text, then a `full_metadata:`
 * line carrying the chart but no `debug_info`.
 */
const liveStream = () => {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      controller.enqueue(
        encoder.encode(
          `data: ${JSON.stringify({
            chunk: "Top 5 Customers by Total Spend",
            session_id: SESSION,
          })}\n\n`,
        ),
      );
      controller.enqueue(
        encoder.encode(
          `full_metadata: ${JSON.stringify({
            response: "Top 5 Customers by Total Spend",
            chat_id: "chat-1",
            chart_output: {
              chart_suggestion: "Bar Chart",
              chart_data: {
                // The spelling the service uses, which the table read as blank.
                data: [
                  { index: "Wei Zhang", value: 7866.82 },
                  { index: "Deshawn Carter", value: 6269.46 },
                ],
                metadata: {
                  x_axis: { label: "CUSTOMER" },
                  y_axis: { label: "TOTAL SPEND (USD)" },
                },
              },
            },
          })}\n\n`,
        ),
      );
      controller.close();
    },
  });
};

/** The same turn as the service stores it — `debug_info` and all. */
const storedThread = {
  data: {
    conversation_data: [
      {
        chat_id: "chat-1",
        role: "user",
        message: "Who are our top 5 customers by total spend?",
      },
      {
        chat_id: "chat-1",
        role: "assistant",
        message: "Top 5 Customers by Total Spend",
        debug_info: {
          sql_query: SQL,
          selected_tables: ["customers", "orders"],
          db_result: {
            columns: [{ name: "name" }, { name: "total_spend" }],
            rows: [
              { name: "Wei Zhang", total_spend: 7866.82 },
              { name: "Deshawn Carter", total_spend: 6269.46 },
            ],
            row_count: 2,
          },
        },
      },
    ],
  },
};

const streamOnce = () => {
  global.fetch = vi.fn().mockResolvedValue({
    headers: { get: () => SESSION },
    body: liveStream(),
    ok: true,
  }) as unknown as typeof fetch;
};

describe("a live Database Agent turn", () => {
  it("is declared reconcilable by the transport", () => {
    expect(nl2sqlChatTransport(AGENT)?.reconcileAfterStream).toBe(true);
  });

  it("shows its SQL, tables and rows without a reload", async () => {
    streamOnce();
    (axios.get as ReturnType<typeof vi.fn>).mockResolvedValue(storedThread);

    const { result } = renderHook(() =>
      useChatStream(nl2sqlChatTransport(AGENT)),
    );

    act(() => {
      result.current.addMessage("Who are our top 5 customers by total spend?");
    });
    await act(async () => {
      await result.current.callStreamAnswer({
        agent_id: AGENT,
        session_id: "",
        query: "Who are our top 5 customers by total spend?",
        stream: true,
      });
    });

    await waitFor(() => {
      const view = normalizeNl2sql(result.current.sessionMessages[1])!;
      expect(view.sqlQuery).toBe(SQL);
      expect(view.tablesUsed).toEqual(["customers", "orders"]);
      // The stored rows, not the chart's points: real column names, real cells.
      expect(view.previewRows).toEqual([
        { name: "Wei Zhang", total_spend: 7866.82 },
        { name: "Deshawn Carter", total_spend: 6269.46 },
      ]);
    });
    // The answer text is the streamed one throughout.
    expect(result.current.sessionMessages[1].message).toBe(
      "Top 5 Customers by Total Spend",
    );
  });

  it("never draws the chart's points as blank cells", async () => {
    streamOnce();
    // Nothing stored yet — the reconcile has nothing to add, which is the
    // window the reader used to see.
    (axios.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { conversation_data: [] },
    });

    const { result } = renderHook(() =>
      useChatStream(nl2sqlChatTransport(AGENT)),
    );

    act(() => {
      result.current.addMessage("Who are our top 5 customers by total spend?");
    });
    await act(async () => {
      await result.current.callStreamAnswer({
        agent_id: AGENT,
        session_id: "",
        query: "Who are our top 5 customers by total spend?",
        stream: true,
      });
    });

    const view = normalizeNl2sql(result.current.sessionMessages[1])!;
    // Read as the service spells them, rather than a row of undefined cells
    // under the axis labels.
    expect(view.previewRows).toEqual([
      { CUSTOMER: "Wei Zhang", "TOTAL SPEND (USD)": 7866.82 },
      { CUSTOMER: "Deshawn Carter", "TOTAL SPEND (USD)": 6269.46 },
    ]);
    expect(result.current.sessionMessages[1].message).toBe(
      "Top 5 Customers by Total Spend",
    );
  });
});
