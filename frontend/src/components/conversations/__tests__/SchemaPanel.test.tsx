import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import SchemaPanel from "../SchemaPanel";

const TABLES = [
  {
    table_name: "customers",
    description: "One row per signed-up customer.",
    is_included: true,
    column_count: 7,
  },
  {
    table_name: "audit_log",
    description: "",
    is_included: false,
    column_count: 4,
  },
];

describe("SchemaPanel", () => {
  it("lists the database's tables with their column counts", () => {
    render(
      <SchemaPanel
        databaseName="northwind_prod"
        tables={TABLES}
        isLoading={false}
        onClose={() => {}}
      />,
    );
    expect(screen.getByText("customers")).toBeInTheDocument();
    expect(screen.getByText("7 columns")).toBeInTheDocument();
    expect(screen.getByText("4 columns")).toBeInTheDocument();
  });

  it("opens a table onto what the agent knows about it", () => {
    render(
      <SchemaPanel
        databaseName="northwind_prod"
        tables={TABLES}
        isLoading={false}
        onClose={() => {}}
      />,
    );
    expect(
      screen.queryByText("One row per signed-up customer."),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /customers/ }));
    expect(
      screen.getByText("One row per signed-up customer."),
    ).toBeInTheDocument();
  });

  it("marks a table the agent is not allowed to query", () => {
    render(
      <SchemaPanel
        databaseName="northwind_prod"
        tables={TABLES}
        isLoading={false}
        onClose={() => {}}
      />,
    );
    expect(screen.getByTitle("Excluded from answers")).toBeInTheDocument();
  });

  it("narrows the list as the reader types", () => {
    render(
      <SchemaPanel
        databaseName="northwind_prod"
        tables={TABLES}
        isLoading={false}
        onClose={() => {}}
      />,
    );
    fireEvent.change(screen.getByLabelText("Search tables"), {
      target: { value: "audit" },
    });
    expect(screen.getByText("audit_log")).toBeInTheDocument();
    expect(screen.queryByText("customers")).not.toBeInTheDocument();
  });

  it("hands the close button back to the screen", () => {
    const onClose = vi.fn();
    render(
      <SchemaPanel
        databaseName="northwind_prod"
        tables={[]}
        isLoading={false}
        onClose={onClose}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Hide schema" }));
    expect(onClose).toHaveBeenCalled();
  });

  it("says so when the database exposes no tables to the agent", () => {
    render(
      <SchemaPanel
        databaseName="northwind_prod"
        tables={[]}
        isLoading={false}
        onClose={() => {}}
      />,
    );
    expect(screen.getByText(/no tables/i)).toBeInTheDocument();
  });
});
