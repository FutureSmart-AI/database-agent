import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import SessionSidebar from "../SessionSidebar";

// `~/lib/fonts` reaches for `next/font/local`, which needs the Next compiler.
vi.mock("@/lib/fonts", () => ({ NL2SQL_FONT_CLASS: "" }));

const SESSIONS = [
  {
    session_id: "s1",
    session_title: "Orders by status",
    created_time: new Date().toISOString(),
    user_id: null,
    from_chat_widget: false,
  },
  {
    session_id: "s2",
    session_title: "Refund rate",
    created_time: new Date().toISOString(),
    user_id: null,
    from_chat_widget: false,
  },
];

const props = {
  sessions: SESSIONS,
  isLoading: false,
  currentId: null,
  onSelect: () => {},
  onNewChat: () => {},
  tabs: [],
};

describe("SessionSidebar delete", () => {
  it("offers a delete on each conversation", () => {
    render(<SessionSidebar {...props} onDelete={vi.fn()} />);
    expect(
      screen.getByRole("button", { name: 'Delete "Orders by status"' }),
    ).toBeInTheDocument();
  });

  it("asks before deleting, and does nothing when the answer is no", () => {
    const onDelete = vi.fn();
    render(<SessionSidebar {...props} onDelete={onDelete} />);

    fireEvent.click(
      screen.getByRole("button", { name: 'Delete "Orders by status"' }),
    );
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Keep it" }));
    expect(onDelete).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("deletes the conversation the reader confirmed", () => {
    const onDelete = vi.fn();
    render(<SessionSidebar {...props} onDelete={onDelete} />);

    fireEvent.click(
      screen.getByRole("button", { name: 'Delete "Refund rate"' }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(onDelete).toHaveBeenCalledWith("s2");
  });

  it("offers no delete on a list the reader may only watch", () => {
    render(<SessionSidebar {...props} />);
    expect(
      screen.queryByRole("button", { name: /^Delete/ }),
    ).not.toBeInTheDocument();
  });
});

describe("SessionSidebar collapse", () => {
  it("folds to a strip that lists no conversation", () => {
    render(<SessionSidebar {...props} collapsed onToggleCollapsed={vi.fn()} />);
    expect(
      screen.getByRole("button", { name: "Expand conversations" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Orders by status")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "New chat" }),
    ).not.toBeInTheDocument();
  });

  it("toggles from either state", () => {
    const onToggleCollapsed = vi.fn();
    const { rerender } = render(
      <SessionSidebar {...props} onToggleCollapsed={onToggleCollapsed} />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Collapse conversations" }),
    );
    rerender(
      <SessionSidebar
        {...props}
        collapsed
        onToggleCollapsed={onToggleCollapsed}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Expand conversations" }),
    );
    expect(onToggleCollapsed).toHaveBeenCalledTimes(2);
  });

  it("draws no handle where the screen cannot collapse the rail", () => {
    render(<SessionSidebar {...props} />);
    expect(
      screen.queryByRole("button", { name: /conversations$/ }),
    ).not.toBeInTheDocument();
  });
});
