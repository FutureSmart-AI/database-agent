import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import ResultTable from "../ResultTable";

const ROWS = [
  {
    id: "7153d846-8a48-4457-b2b0-f1228a2678bd",
    email: "ajjv@gmail.com",
    first_name: "Ajju",
    phone: "+39 345 678 9123",
    created_at: "2025-11-11T16:57:01",
    revenue: 120,
  },
];

const COLUMNS = ["id", "email", "first_name", "phone", "created_at", "revenue"];

const cell = (text: string) => screen.getByText(text);

describe("ResultTable", () => {
  it("sets ids, phones, timestamps and numbers in mono, prose in the body face", () => {
    render(
      <ResultTable rows={ROWS} columns={COLUMNS} totalRows={1} query="" />,
    );
    expect(cell(ROWS[0].id)).toHaveClass("font-mono");
    expect(cell("+39 345 678 9123")).toHaveClass("font-mono");
    expect(cell("2025-11-11T16:57:01")).toHaveClass("font-mono");
    expect(cell("120")).toHaveClass("font-mono");

    expect(cell("ajjv@gmail.com")).not.toHaveClass("font-mono");
    expect(cell("Ajju")).not.toHaveClass("font-mono");
  });

  it("greys the row's identity and its timestamps, and left-aligns every cell", () => {
    render(
      <ResultTable rows={ROWS} columns={COLUMNS} totalRows={1} query="" />,
    );
    expect(cell(ROWS[0].id)).toHaveClass("text-n2s-ink-3");
    expect(cell("2025-11-11T16:57:01")).toHaveClass("text-n2s-ink-3");
    expect(cell("Ajju")).toHaveClass("text-n2s-ink-2");
    // Numbers are not pushed to the right edge — the artifact reads left.
    expect(cell("120")).toHaveClass("text-left");
    expect(cell("120")).not.toHaveClass("text-right");
  });

  it("counts the rows the artifact's way", () => {
    render(
      <ResultTable rows={ROWS} columns={COLUMNS} totalRows={1} query="" />,
    );
    expect(screen.getByText("Showing 1–1 of 1")).toBeInTheDocument();
  });

  it("says what a filter narrowed away", () => {
    render(
      <ResultTable rows={ROWS} columns={COLUMNS} totalRows={9} query="ajju" />,
    );
    expect(
      screen.getByText("Showing 1–1 of 1 (filtered from 9)"),
    ).toBeInTheDocument();
  });
});
