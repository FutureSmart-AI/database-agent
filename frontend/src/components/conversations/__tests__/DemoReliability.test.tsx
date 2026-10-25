import { forwardRef, useImperativeHandle, useRef, type ReactNode } from "react";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import DemoAllowanceNote from "@/components/demo/DemoAllowanceNote";
import { includedTableCount } from "@/data/agents";
import { demoBlocked, type DemoAllowance } from "@/data/demo";
import type { AgentDatabase } from "@/data/types";
import axios from "@/platform/utils/axios";

import ChatEmptyState from "../ChatEmptyState";
import Composer from "../Composer";
import FollowUps from "../FollowUps";
import ReportProblem from "../ReportProblem";

vi.mock("@/platform/utils/axios", () => ({
  default: { get: vi.fn(), post: vi.fn() },
}));

// The real input focuses its textarea and puts the caret at the end; this
// stand-in exposes the same handle.
vi.mock("@/platform/components/conversations/MessageBox", () => ({
  default: forwardRef<{ focus: () => void }, { inputValue: string }>(
    function MessageBox({ inputValue }, ref) {
      const area = useRef<HTMLTextAreaElement>(null);
      useImperativeHandle(ref, () => ({ focus: () => area.current?.focus() }));
      return (
        <textarea aria-label="Message" ref={area} value={inputValue} readOnly />
      );
    },
  ),
}));

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

const mockedPost = vi.mocked(axios.post);

function withClient(node: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{node}</QueryClientProvider>;
}

describe("a picked suggestion can be sent with Enter", () => {
  it("moves focus into the input when a question is put there", () => {
    const props = { value: "", onChange: vi.fn(), onSend: vi.fn() };
    const { rerender } = render(
      <>
        <button type="button">suggestion</button>
        <Composer {...props} />
      </>,
    );
    screen.getByText("suggestion").focus();
    rerender(
      <>
        <button type="button">suggestion</button>
        <Composer {...props} value="Top five customers" focusSignal={1} />
      </>,
    );
    expect(document.activeElement).toBe(screen.getByLabelText("Message"));
  });

  it("does not take focus on first render", () => {
    render(<Composer value="" onChange={vi.fn()} onSend={vi.fn()} />);
    expect(document.activeElement).not.toBe(screen.getByLabelText("Message"));
  });
});

describe("suggestions while no question can be sent", () => {
  it("starter questions are shown but cannot be picked", () => {
    const onPick = vi.fn();
    render(
      <ChatEmptyState
        suggestions={["Top customers"]}
        onPick={onPick}
        disabled
      />,
    );
    const chip = screen.getByRole("button", { name: "Top customers" });
    expect(chip).toBeDisabled();
    fireEvent.click(chip);
    expect(onPick).not.toHaveBeenCalled();
  });

  it("follow-ups are not offered", () => {
    render(
      <FollowUps questions={["Only the top two"]} onPick={vi.fn()} disabled />,
    );
    expect(screen.queryByText("Only the top two")).toBeNull();
  });
});

const internal: DemoAllowance = {
  audience: "internal",
  unlimited: true,
  daily_limit: null,
  daily_used: 40,
  daily_remaining: null,
  daily_resets_at: null,
  total_limit: null,
  total_used: 300,
  total_remaining: null,
  budget_open: true,
};

describe("internal accounts", () => {
  it("are never blocked and are told they are unlimited", () => {
    expect(demoBlocked(internal)).toBeNull();
    render(<DemoAllowanceNote allowance={internal} variant="bar" />);
    expect(
      screen.getByText(/Unlimited questions for FutureSmart team accounts/),
    ).toBeInTheDocument();
  });

  it("public users still see their counts and limits", () => {
    const publicUser: DemoAllowance = {
      ...internal,
      audience: "public",
      unlimited: false,
      daily_limit: 20,
      daily_used: 20,
      daily_remaining: 0,
      total_limit: 100,
      total_used: 20,
      total_remaining: 80,
    };
    expect(demoBlocked(publicUser)).toMatch(/today's 20 free questions/);
  });
});

describe("header table count", () => {
  const db = (count: number | null) =>
    ({ included_table_count: count }) as AgentDatabase;

  it("adds up the tables the agent may read", () => {
    expect(includedTableCount([db(7)])).toBe(7);
    expect(includedTableCount([db(7), db(null), db(2)])).toBe(9);
  });

  it("is unknown, not zero, when no database reports a count", () => {
    expect(includedTableCount([db(null)])).toBeNull();
    expect(includedTableCount([])).toBeNull();
  });
});

describe("Report a problem", () => {
  beforeEach(() => mockedPost.mockReset());

  it("sends what went wrong for this answer and shows the report id", async () => {
    mockedPost.mockResolvedValue({
      data: { report_id: "RPT_1A2B3C4D", status: "open" },
    });
    render(
      withClient(
        <ReportProblem agentId="NL2SQL_X" sessionId="S1" chatId="C2" />,
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "Report a problem" }));
    fireEvent.click(screen.getByText("Chart missing or wrong"));
    const send = screen.getByRole("button", { name: "Send report" });
    expect(send).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Describe the problem"), {
      target: { value: "The chart disappeared on the follow-up." },
    });
    fireEvent.change(screen.getByLabelText("What did you expect? (optional)"), {
      target: { value: "Two bars" },
    });
    fireEvent.click(send);
    await waitFor(() =>
      expect(screen.getByText("RPT_1A2B3C4D")).toBeInTheDocument(),
    );
    expect(mockedPost).toHaveBeenCalledWith(
      "/nl2sql/api/v1/agents/NL2SQL_X/reports",
      {
        session_id: "S1",
        chat_id: "C2",
        category: "wrong_chart",
        note: "The chart disappeared on the follow-up.",
        expected: "Two bars",
      },
    );
  });
});
