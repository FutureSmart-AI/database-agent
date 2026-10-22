import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import ChatEmptyState from "../ChatEmptyState";

describe("ChatEmptyState", () => {
  it("names the database the agent will query", () => {
    render(
      <ChatEmptyState
        databaseName="northwind_prod"
        suggestions={[]}
        onPick={() => {}}
      />,
    );
    expect(screen.getByText("northwind_prod")).toBeInTheDocument();
  });

  it("reads sensibly before the database is known", () => {
    render(<ChatEmptyState suggestions={[]} onPick={() => {}} />);
    expect(screen.getByText(/against your database/)).toBeInTheDocument();
  });

  it("offers the agent's starter questions and hands one back", () => {
    const onPick = vi.fn();
    render(
      <ChatEmptyState
        suggestions={["Which region refunded most?"]}
        onPick={onPick}
      />,
    );
    expect(screen.getByText("Try one of these")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Which region refunded most?" }),
    );
    expect(onPick).toHaveBeenCalledWith("Which region refunded most?");
  });

  it("omits the suggestions block when the agent configured none", () => {
    render(<ChatEmptyState suggestions={[]} onPick={() => {}} />);
    expect(screen.queryByText("Try one of these")).not.toBeInTheDocument();
  });
});
