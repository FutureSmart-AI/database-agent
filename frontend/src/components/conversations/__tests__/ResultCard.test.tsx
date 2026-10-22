import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Nl2sqlView } from "@/platform/components/conversations/nl2sql/normalizeNl2sql";

import ResultCard from "../ResultCard";

vi.mock("@/platform/components/conversations/nl2sql/FullDatasetModal", () => ({
  default: () => null,
}));

const ROWS = [
  { email: "a@x.com", first_name: "Ada", revenue: 120 },
  { email: "b@x.com", first_name: "Bo", revenue: 80 },
  { email: "c@x.com", first_name: "Cy", revenue: 60 },
  { email: "d@x.com", first_name: "Di", revenue: 40 },
  { email: "e@x.com", first_name: "Ed", revenue: 20 },
  { email: "f@x.com", first_name: "Fay", revenue: 10 },
];

const view = (over: Partial<Nl2sqlView> = {}): Nl2sqlView => ({
  tablesUsed: ["customers"],
  rowCountIsPreview: false,
  previewRows: ROWS,
  rowCount: ROWS.length,
  ...over,
});

describe("ResultCard", () => {
  it("names the table it read and how many rows came back", () => {
    render(<ResultCard view={view()} />);
    expect(screen.getByText("customers")).toBeInTheDocument();
    expect(screen.getByText("6 rows")).toBeInTheDocument();
  });

  it("paginates at five rows and moves between pages", () => {
    render(<ResultCard view={view()} />);
    expect(screen.getByText("Showing 1–5 of 6")).toBeInTheDocument();
    expect(screen.queryByText("f@x.com")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByText("Showing 6–6 of 6")).toBeInTheDocument();
    expect(screen.getByText("f@x.com")).toBeInTheDocument();
  });

  it("filters rows across the visible columns", () => {
    render(<ResultCard view={view()} />);
    fireEvent.change(screen.getByLabelText("Filter rows"), {
      target: { value: "Ada" },
    });
    expect(screen.getByText("a@x.com")).toBeInTheDocument();
    expect(screen.queryByText("b@x.com")).not.toBeInTheDocument();
    expect(screen.getByText(/filtered from 6/)).toBeInTheDocument();
    // The card's own count reports the filter, as in the artifact.
    expect(screen.getByText("1 of 6 rows")).toBeInTheDocument();
  });

  it("hides a column from the columns menu, and keeps the last one", () => {
    render(<ResultCard view={view()} />);
    fireEvent.click(screen.getByRole("button", { name: /Columns/ }));

    fireEvent.click(screen.getByRole("button", { name: "Hide email" }));
    expect(
      screen.queryByRole("columnheader", { name: /email/ }),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Hide first_name" }));
    // One column left — it must not be hideable.
    expect(screen.getByRole("button", { name: "Hide revenue" })).toBeDisabled();
  });

  it("sorts by a column and flips direction on a second click", () => {
    render(<ResultCard view={view()} />);
    const header = screen.getByRole("button", { name: /revenue/ });

    fireEvent.click(header);
    const ascending = screen.getAllByRole("row")[1];
    expect(within(ascending).getByText("10")).toBeInTheDocument();

    fireEvent.click(header);
    const descending = screen.getAllByRole("row")[1];
    expect(within(descending).getByText("120")).toBeInTheDocument();
  });

  it("offers the chart view only when the answer carried chart data", () => {
    const { rerender } = render(<ResultCard view={view()} />);
    expect(
      screen.queryByRole("tab", { name: "Chart" }),
    ).not.toBeInTheDocument();

    rerender(
      <ResultCard
        view={view({
          chart: {
            suggestion: "bar chart",
            data: [{ x: "North", y: 10 }],
          },
        })}
      />,
    );
    expect(screen.getByRole("tab", { name: "Chart" })).toBeInTheDocument();
  });

  it("says the export is preview-only when no full dataset was staged", () => {
    render(<ResultCard view={view()} />);
    expect(
      screen.getByRole("button", { name: /CSV preview/ }),
    ).toBeInTheDocument();
  });

  it("offers the full export when the backend staged one", () => {
    render(
      <ResultCard
        view={view({ resultS3Url: "https://example.com/result.csv" })}
      />,
    );
    expect(screen.getByRole("button", { name: /^CSV$/ })).toBeInTheDocument();
  });

  it("draws nothing when there are neither rows nor a chart", () => {
    const { container } = render(
      <ResultCard view={view({ previewRows: [], rowCount: 0 })} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});

describe("ResultCard columns", () => {
  const WIDE = [
    {
      id: "u-1",
      email: "a@x.com",
      first_name: "Ada",
      updated_at: "2026-05-01",
    },
  ];

  it("folds the id and last-written columns away, as the artifact draws it", () => {
    render(<ResultCard view={view({ previewRows: WIDE, rowCount: 1 })} />);
    expect(
      screen.queryByRole("columnheader", { name: /id/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("columnheader", { name: /updated_at/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: /email/ }),
    ).toBeInTheDocument();
  });

  it("says how many columns are folded, and gives them back", () => {
    render(<ResultCard view={view({ previewRows: WIDE, rowCount: 1 })} />);
    const columnsButton = screen.getByRole("button", { name: /Columns/ });
    expect(columnsButton).toHaveTextContent("2");

    fireEvent.click(columnsButton);
    fireEvent.click(screen.getByRole("button", { name: "Show id" }));
    expect(
      screen.getByRole("columnheader", { name: /id/ }),
    ).toBeInTheDocument();
  });

  it("folds nothing when there would be nothing left", () => {
    render(
      <ResultCard view={view({ previewRows: [{ id: "u-1" }], rowCount: 1 })} />,
    );
    expect(
      screen.getByRole("columnheader", { name: /id/ }),
    ).toBeInTheDocument();
  });
});

/**
 * The query and the payload used to live in a second card underneath this one
 * ("How I got this"), which spent two boxes and two bars of chrome on one
 * answer. They are tabs of this card now, and gated exactly as they were.
 */
describe("ResultCard query and payload", () => {
  const withSql = view({ sqlQuery: "SELECT email FROM customers LIMIT 10" });

  it("shows the generated query on its own tab", () => {
    render(<ResultCard view={withSql} showQuery raw={{ chat_id: "abc123" }} />);
    fireEvent.click(screen.getByRole("tab", { name: "Query" }));
    expect(screen.getByText(/SELECT/)).toBeInTheDocument();
  });

  it("hides the query when the agent does not show it", () => {
    render(<ResultCard view={withSql} showQuery={false} />);
    expect(
      screen.queryByRole("tab", { name: "Query" }),
    ).not.toBeInTheDocument();
  });

  it("hides the payload unless the agent exposes it", () => {
    const { rerender } = render(
      <ResultCard view={withSql} showQuery raw={{ chat_id: "abc123" }} />,
    );
    expect(screen.queryByRole("tab", { name: "Raw" })).not.toBeInTheDocument();

    rerender(
      <ResultCard
        view={withSql}
        showQuery
        raw={{ chat_id: "abc123" }}
        rawEnabled
      />,
    );
    fireEvent.click(screen.getByRole("tab", { name: "Raw" }));
    expect(screen.getByText(/abc123/)).toBeInTheDocument();
  });

  it("withholds the rows but keeps the query when results are off", () => {
    render(<ResultCard view={withSql} showQuery showResults={false} />);
    expect(screen.queryByRole("tab", { name: "Data" })).not.toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Query" })).toBeInTheDocument();
  });

  it("draws nothing when every tab is gated off", () => {
    const { container } = render(
      <ResultCard view={withSql} showQuery={false} showResults={false} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});

/**
 * The service suggests one reading of a result; the reader gets all of them.
 * The suggestion came from the question, not from the shape of the rows.
 */
describe("ResultCard chart types", () => {
  const charted = () =>
    view({
      chart: {
        suggestion: "bar chart",
        data: [
          { x: "North", y: 10 },
          { x: "South", y: 6 },
        ],
      },
    });

  it("offers every reading of the result, with the suggested one selected", () => {
    render(<ResultCard view={charted()} />);
    fireEvent.click(screen.getByRole("tab", { name: "Chart" }));

    const picker = screen.getByRole("group", { name: "Chart type" });
    for (const label of [
      "Bar chart",
      "Column chart",
      "Line chart",
      "Area chart",
      "Pie chart",
      "Donut chart",
      "Scatter chart",
    ]) {
      expect(
        within(picker).getByRole("button", { name: label }),
      ).toBeInTheDocument();
    }
    expect(
      within(picker).getByRole("button", { name: "Bar chart" }),
    ).toHaveAttribute("aria-pressed", "true");
  });

  it("redraws the result as the type the reader picks", () => {
    render(<ResultCard view={charted()} />);
    fireEvent.click(screen.getByRole("tab", { name: "Chart" }));

    fireEvent.click(screen.getByRole("button", { name: "Pie chart" }));
    expect(screen.getByRole("button", { name: "Pie chart" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    // The suggestion is still on screen, so the card never claims the service
    // asked for the view the reader chose.
    expect(screen.getByText("Suggested chart:")).toBeInTheDocument();
    expect(screen.getByText("Shown as")).toBeInTheDocument();
  });

  it("withholds the share readings when a value is negative", () => {
    render(
      <ResultCard
        view={view({
          chart: {
            suggestion: "bar chart",
            data: [
              { x: "North", y: 10 },
              { x: "South", y: -4 },
            ],
          },
        })}
      />,
    );
    fireEvent.click(screen.getByRole("tab", { name: "Chart" }));
    expect(
      screen.queryByRole("button", { name: "Pie chart" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Line chart" }),
    ).toBeInTheDocument();
  });
});
