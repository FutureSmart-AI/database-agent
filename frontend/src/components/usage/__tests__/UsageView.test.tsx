import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AggregateGroup, UsageFilters, UsageGroupBy } from "@/data/usage";

import UsageView from "../UsageView";

/**
 * The Usage screen, element by element, against the API contract behind it.
 *
 * Every figure here comes out of a fixture shaped exactly as `/v1/aggregate`,
 * `/v1/trend` and `/v1/owners/me/limits` answer, and the pure helpers in
 * `~/data/usage` are left real — so a test that passes proves the screen reads
 * the response the service actually sends, not a convenient reshaping of it.
 *
 * The contract rules asserted: no ungrouped total (`group_by=key_type`, summed),
 * cost from `token_rate_usd`, no `service_type` grouping anywhere, `null` model
 * groups kept and reported, dense trend buckets plotted including zeros, the
 * Custom Filters mapping (Agent → `agent_id`, Operation → `label`, Functional
 * Label → `phase`), and both controls disabled on Limits.
 */

const TOKEN_RATE = 0.0000038;

const metrics = (
  total: number,
  input: number,
  output: number,
  seconds?: number,
) => [
  {
    metric_name: "total_tokens" as const,
    total,
    avg: total,
    min: 0,
    max: total,
    count: 1,
  },
  {
    metric_name: "input_tokens" as const,
    total: input,
    avg: input,
    min: 0,
    max: input,
    count: 1,
  },
  {
    metric_name: "output_tokens" as const,
    total: output,
    avg: output,
    min: 0,
    max: output,
    count: 1,
  },
  ...(seconds === undefined
    ? []
    : [
        {
          metric_name: "execution_time_seconds" as const,
          total: seconds,
          avg: seconds,
          min: seconds,
          max: seconds,
          count: 1,
        },
      ]),
];

const KEY_TYPE_GROUPS: AggregateGroup[] = [
  {
    key_type: "platform-key",
    event_count: 30,
    metrics: metrics(900_000, 800_000, 100_000),
  } as AggregateGroup,
  {
    key_type: "owner-key",
    event_count: 12,
    metrics: metrics(100_000, 90_000, 10_000),
  } as AggregateGroup,
];

const OPERATION_GROUPS: AggregateGroup[] = [
  {
    operation: "llm_call",
    event_count: 32,
    metrics: metrics(1_000_000, 890_000, 110_000),
  },
  { operation: "db_query", event_count: 7, metrics: [] },
  { operation: "code_execution", event_count: 3, metrics: [] },
] as AggregateGroup[];

const LABEL_GROUPS: AggregateGroup[] = [
  {
    label: "sql_generation",
    event_count: 20,
    metrics: metrics(600_000, 500_000, 100_000, 1.46),
  },
  {
    label: "final_answer",
    event_count: 12,
    metrics: metrics(400_000, 390_000, 10_000, 0.56),
  },
] as AggregateGroup[];

const MODEL_GROUPS: AggregateGroup[] = [
  {
    model: "openai/gpt-oss-120b",
    provider: "groq",
    event_count: 32,
    metrics: metrics(1_000_000, 890_000, 110_000),
  },
  // Real data, not an error: a `db_query` event carries no model at all.
  { model: null, provider: null, event_count: 10, metrics: [] },
] as AggregateGroup[];

const AGENT_GROUPS: AggregateGroup[] = [
  {
    agent_id: "NL2SQL_ABC",
    event_count: 42,
    metrics: metrics(1_000_000, 890_000, 110_000),
  },
  // Real: some operations are recorded against the workspace, not an agent.
  { agent_id: null, event_count: 5, metrics: [] },
] as AggregateGroup[];

const PHASE_GROUPS: AggregateGroup[] = [
  { phase: "Answering", event_count: 12, metrics: [] },
  { phase: "Extracting", event_count: 20, metrics: [] },
] as AggregateGroup[];

/** Dense and oldest-first, exactly as `/v1/trend` returns it. */
const SERIES = [
  {
    bucket_start: "2026-08-24T10:14:02+00:00",
    bucket_end: "2026-08-25T10:14:02+00:00",
    event_count: 0,
    metrics: {},
  },
  {
    bucket_start: "2026-08-25T10:14:02+00:00",
    bucket_end: "2026-08-26T10:14:02+00:00",
    event_count: 12,
    metrics: { total_tokens: 8_421 },
  },
];

const LIMITS = {
  owner_id: "me",
  tier: { name: "Trial", tier_type: "trial", is_default: true },
  billing_window: {
    days: 30,
    start: "2026-07-27T10:14:02+00:00",
    end: "2026-08-26T10:14:02+00:00",
  },
  own_credentials: ["groq"],
  token_rate_usd: TOKEN_RATE,
  groups: [],
  exceeded: [],
};

interface AggregateCall {
  groupBy: UsageGroupBy[];
  period: string;
  source: string;
  filters: UsageFilters;
  enabled: boolean;
}

const aggregateCalls: AggregateCall[] = [];
const trendCalls: Array<{ bucket: string; filters: UsageFilters }> = [];
let emptyTotals = false;

function groupsFor(groupBy: UsageGroupBy[]): AggregateGroup[] {
  const key = groupBy.join(",");
  if (key === "operation") return OPERATION_GROUPS;
  if (key === "label") return LABEL_GROUPS;
  if (key === "model,provider") return MODEL_GROUPS;
  if (key === "agent_id") return AGENT_GROUPS;
  if (key === "phase") return PHASE_GROUPS;
  return [];
}

vi.mock("@/data/usage", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/data/usage")>();

  return {
    ...actual,
    useOwnerLimits: () => ({ data: LIMITS, isLoading: false, error: null }),
    useUsageTotals: () => {
      const groups = emptyTotals ? [] : KEY_TYPE_GROUPS;
      const platform = actual.sumGroups(
        groups.filter((group) => group.key_type === "platform-key"),
      );
      const owner = actual.sumGroups(
        groups.filter((group) => group.key_type === "owner-key"),
      );
      const total = actual.sumGroups(groups);
      return {
        data: { platform, owner, total, selected: total },
        isLoading: false,
        error: null,
      };
    },
    useUsageAggregate: (
      groupBy: UsageGroupBy[],
      period: string,
      source: string,
      filters: UsageFilters = {},
      enabled = true,
    ) => {
      aggregateCalls.push({ groupBy, period, source, filters, enabled });
      return {
        data: { group_by: groupBy, groups: groupsFor(groupBy) },
        isLoading: false,
        error: null,
      };
    },
    useUsageTrend: (
      _period: string,
      _source: string,
      bucket: string,
      filters: UsageFilters = {},
    ) => {
      trendCalls.push({ bucket, filters });
      return {
        data: { bucket, bucket_days: 1, days: 30, series: SERIES },
        isLoading: false,
        error: null,
      };
    },
  };
});

vi.mock("@/data/useAgents", () => ({
  useAgents: () => ({
    agents: [{ agent_id: "NL2SQL_ABC", name: "Sales database" }],
  }),
}));

vi.mock("../PlanLimits", () => ({
  default: () => <div>Plan limits panel</div>,
}));

const callsFor = (groupBy: string) =>
  aggregateCalls.filter((call) => call.groupBy.join(",") === groupBy);

/**
 * A metric card, by the thing it opens. Its accessible name is its own text —
 * the label, the figure and the footnote — so the `title` is what identifies it
 * without pinning the test to a formatted number.
 */
const metricCard = (label: string) =>
  screen.getByTitle(`Open the model breakdown for ${label}`);

/** The cost strip, which is the one place the arithmetic is shown. */
const costStrip = () =>
  screen
    .getByRole("heading", { level: 2, name: "Total estimated cost" })
    .closest("section")!;

beforeEach(() => {
  aggregateCalls.length = 0;
  trendCalls.length = 0;
  emptyTotals = false;
  window.location.hash = "";
});

afterEach(() => {
  window.location.hash = "";
});

/* ── the shell ──────────────────────────────────────────────────────────── */

describe("the screen shell", () => {
  it("puts the heading, the link back and both controls above the rail", () => {
    render(<UsageView />);

    expect(
      screen.getByRole("link", { name: "Back to Home" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 1, name: "Account Overview" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /Showing TOTAL CONSUMPTIONS — platform plus your own keys/,
      ),
    ).toBeInTheDocument();

    expect(screen.getByLabelText("Consumption source")).toBeEnabled();
    expect(screen.getByLabelText("Usage period")).toBeEnabled();
  });

  it("offers the four rail sections the design names", () => {
    render(<UsageView />);

    const rail = screen.getByRole("navigation", { name: "Usage sections" });
    expect(
      within(rail)
        .getAllByRole("button")
        .map((button) => button.textContent),
    ).toEqual(["Overview", "Limits", "Agents", "Custom Filters"]);
  });

  it("names the active consumption source in the sub-line", () => {
    render(<UsageView />);

    fireEvent.change(screen.getByLabelText("Consumption source"), {
      target: { value: "owner" },
    });
    expect(
      screen.getByText(
        /Showing OWNER CONSUMPTIONS only — work billed to your own provider credentials/,
      ),
    ).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Consumption source"), {
      target: { value: "platform" },
    });
    expect(
      screen.getByText(
        /Showing PLATFORM CONSUMPTIONS only — work billed to FutureSmart platform keys/,
      ),
    ).toBeInTheDocument();
  });

  it("shows the top of a section when it opens", () => {
    // The sections are different lengths, so opening one from a scrolled
    // position used to start it past its own heading. The view finds the
    // scroll container by walking up, because it belongs to the shell.
    const scroller = document.createElement("div");
    scroller.style.overflowY = "auto";
    const scrollTo = vi.fn();
    scroller.scrollTo = scrollTo;
    document.body.appendChild(scroller);

    render(<UsageView />, { container: scroller });

    fireEvent.click(screen.getByRole("button", { name: "Limits" }));
    expect(scrollTo).toHaveBeenCalledWith({ top: 0 });
  });

  it("opens a section straight from the fragment and writes it back", () => {
    window.location.hash = "#agents";
    render(<UsageView />);

    expect(
      screen.getByRole("heading", { level: 1, name: "Agents" }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Custom Filters" }));
    expect(window.location.hash).toBe("#filters");
  });
});

/* ── the Limits tab's disabled controls ─────────────────────────────────── */

describe("the Limits tab", () => {
  it("disables both controls, because neither applies to a ceiling", () => {
    render(<UsageView />);
    fireEvent.click(screen.getByRole("button", { name: "Limits" }));

    // A limit counts every request whichever key paid for it, and its window is
    // fixed in `billing_window` — so a live control here would be silently
    // ignored rather than honoured.
    const source = screen.getByLabelText("Consumption source");
    const period = screen.getByLabelText("Usage period");
    expect(source).toBeDisabled();
    expect(period).toBeDisabled();
    expect(
      screen.getByText("Consumption source (not applied to Limits)"),
    ).toBeInTheDocument();
    expect(screen.getByText("Period (fixed on Limits)")).toBeInTheDocument();
    expect(
      screen.getByText(
        /The consumption-source filter does not apply here — a limit is enforced against what the platform served, whichever key paid for it/,
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Plan limits panel")).toBeInTheDocument();
  });
});

/* ── Overview ───────────────────────────────────────────────────────────── */

describe("Overview", () => {
  it("shows the cost as platform plus own keys, priced at the workspace rate", () => {
    render(<UsageView />);

    // 900,000 and 100,000 tokens at $0.0000038 → $3.42 + $0.38 = $3.80, and the
    // total IS that sum: there is no total call to disagree with it.
    const strip = costStrip();
    expect(within(strip).getByText("$3.42")).toBeInTheDocument();
    expect(within(strip).getByText("$0.38")).toBeInTheDocument();
    expect(within(strip).getByText("$3.80")).toBeInTheDocument();
    expect(
      screen.getByText(/priced at \$0\.0000038 per token/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /Platform spend plus spend billed to your own provider keys/,
      ),
    ).toBeInTheDocument();
  });

  it("shows one side only, and says so, when a single source is selected", () => {
    render(<UsageView />);
    fireEvent.change(screen.getByLabelText("Consumption source"), {
      target: { value: "platform" },
    });

    const strip = costStrip();
    expect(within(strip).queryByText("$3.80")).not.toBeInTheDocument();
    expect(within(strip).getByText("$3.42")).toBeInTheDocument();
    expect(
      screen.getByText(
        /Platform consumption only — spend billed to your own provider keys is not included in this figure/,
      ),
    ).toBeInTheDocument();
  });

  it("reads the four account figures off the key_type totals", () => {
    render(<UsageView />);

    const card = (label: string) => metricCard(label);

    expect(card("Total Tokens")).toHaveTextContent("1.0M");
    expect(card("Input Tokens")).toHaveTextContent("890.0K");
    expect(card("Output Tokens")).toHaveTextContent("110.0K");
    // `event_count` is the Requests figure, summed across both key types.
    expect(card("Requests")).toHaveTextContent("42");
  });

  it("counts the two non-model operations by their exact operation value", () => {
    render(<UsageView />);

    // Matched on `db_query` and `code_execution`, never on a substring like
    // "sql" — which would pick up the LLM call that writes the SQL.
    expect(metricCard("Database queries")).toHaveTextContent("7");
    expect(metricCard("Code executions")).toHaveTextContent("3");
    expect(screen.getByText("Databases")).toBeInTheDocument();
  });

  it("lists every model that served a request and reports the ones with none", () => {
    render(<UsageView />);

    expect(screen.getByText("openai/gpt-oss-120b")).toBeInTheDocument();
    expect(screen.getByText("groq")).toBeInTheDocument();
    // The `model: null` group is counted, not dropped — dropping it would make
    // this table report less usage than the card above it.
    expect(
      screen.getByText(
        /A further 10 operations ran without a model — database queries and code executions are recorded with no model or provider/,
      ),
    ).toBeInTheDocument();
  });

  it("breaks the pipeline down by label, with the service's own latency", () => {
    render(<UsageView />);

    expect(screen.getByText("Per-Node Breakdown")).toBeInTheDocument();
    const row = screen.getByText("sql_generation").closest("tr")!;
    expect(row).toHaveTextContent("20");
    // 20 of 32 calls.
    expect(row).toHaveTextContent("63%");
    // `execution_time_seconds.avg` of 1.46s, in the app's own duration format.
    expect(row).toHaveTextContent("1.46s");
    expect(callsFor("label")[0].groupBy).toEqual(["label"]);
  });

  it("splits billed operations by operation in the service breakdown", () => {
    render(<UsageView />);

    expect(screen.getByText("Service Breakdown")).toBeInTheDocument();
    // 32 / 42 llm_call, 7 / 42 db_query, 3 / 42 code_execution.
    expect(screen.getByText("76.2%")).toBeInTheDocument();
    expect(screen.getByText("16.7%")).toBeInTheDocument();
    expect(screen.getByText("7.1%")).toBeInTheDocument();
  });

  it("offers only the buckets the trend endpoint accepts", () => {
    render(<UsageView />);

    const granularity = screen.getByLabelText("Trend granularity");
    expect(
      Array.from(granularity.querySelectorAll("option")).map(
        (option) => option.textContent,
      ),
    ).toEqual(["Daily", "Weekly", "Monthly"]);
    // An hourly option was offered here until it was checked: `/v1/trend`
    // 422s on it.
    expect(screen.queryByText("Hourly")).not.toBeInTheDocument();

    fireEvent.change(granularity, { target: { value: "week" } });
    expect(trendCalls.at(-1)!.bucket).toBe("week");
  });

  it("says nothing was recorded rather than showing zeroed cards", () => {
    emptyTotals = true;
    render(<UsageView />);

    expect(
      screen.getByText("Nothing recorded for Total Consumptions"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/No usage was billed to this source in last 30 days/),
    ).toBeInTheDocument();
  });
});

/* ── Agents ─────────────────────────────────────────────────────────────── */

describe("Agents", () => {
  it("joins the agent's name onto the id the aggregate returns", () => {
    render(<UsageView />);
    fireEvent.click(screen.getByRole("button", { name: "Agents" }));

    // Agent names are not in the aggregate — `group_by=agent_id` returns ids,
    // and the names come from the agents list.
    const row = screen.getByText("NL2SQL_ABC").closest("tr")!;
    expect(row).toHaveTextContent("Sales database");
    expect(row).toHaveTextContent("42");
    expect(row).toHaveTextContent("1.0M");
    expect(row).toHaveTextContent("$3.80");
    expect(callsFor("agent_id").some((call) => call.enabled)).toBe(true);
  });

  it("reports operations recorded against no agent instead of dropping them", () => {
    render(<UsageView />);
    fireEvent.click(screen.getByRole("button", { name: "Agents" }));

    // Without this the table reads "no agent usage" while the Overview reports
    // requests for the same period — two screens disagreeing is worse than a
    // footnote.
    expect(
      screen.getByText(
        /A further 5 operations were recorded against the workspace rather than a single agent/,
      ),
    ).toBeInTheDocument();
  });

  it("opens the model breakdown for one agent from its row", () => {
    render(<UsageView />);
    fireEvent.click(screen.getByRole("button", { name: "Agents" }));
    fireEvent.click(screen.getByText("Sales database"));

    const drawer = screen.getByRole("dialog");
    expect(drawer).toHaveTextContent("Breakdown by model and provider");
    expect(drawer).toHaveTextContent("Sales database");
    // The drawer asks the one grouping the contract names for a drawer, with
    // the row's own filter carried through.
    const call = callsFor("model,provider").at(-1)!;
    expect(call.filters).toEqual({ agent_id: "NL2SQL_ABC" });
  });
});

/* ── Custom Filters ─────────────────────────────────────────────────────── */

describe("Custom Filters", () => {
  it("offers exactly the three facets, and no service facet at all", () => {
    render(<UsageView />);
    fireEvent.click(screen.getByRole("button", { name: "Custom Filters" }));

    expect(screen.getByLabelText("Filter by agent")).toBeInTheDocument();
    expect(screen.getByLabelText("Filter by operation")).toBeInTheDocument();
    expect(
      screen.getByLabelText("Filter by functional label"),
    ).toBeInTheDocument();
    // `group_by=service_type` is a 422: every row here is `nl2sql`, so the
    // grouping would always be one group and the service refuses it.
    expect(screen.queryByText("Service")).not.toBeInTheDocument();
    expect(
      aggregateCalls.every(
        (call) => !call.groupBy.includes("service_type" as UsageGroupBy),
      ),
    ).toBe(true);
  });

  it("builds the facet options from the values the data actually has", () => {
    render(<UsageView />);
    fireEvent.click(screen.getByRole("button", { name: "Custom Filters" }));

    const operations = Array.from(
      screen.getByLabelText("Filter by operation").querySelectorAll("option"),
    ).map((option) => option.textContent);
    expect(operations).toEqual([
      "All operations",
      "final_answer",
      "sql_generation",
    ]);

    const labels = Array.from(
      screen
        .getByLabelText("Filter by functional label")
        .querySelectorAll("option"),
    ).map((option) => option.textContent);
    expect(labels).toEqual(["All labels", "Answering", "Extracting"]);
  });

  it("sends Operation as label and Functional Label as phase", () => {
    render(<UsageView />);
    fireEvent.click(screen.getByRole("button", { name: "Custom Filters" }));

    fireEvent.change(screen.getByLabelText("Filter by operation"), {
      target: { value: "sql_generation" },
    });
    fireEvent.change(screen.getByLabelText("Filter by functional label"), {
      target: { value: "Answering" },
    });
    fireEvent.change(screen.getByLabelText("Filter by agent"), {
      target: { value: "NL2SQL_ABC" },
    });

    // The mapping the contract states: the control called Operation narrows by
    // `label`, and the one called Functional Label narrows by `phase`.
    expect(callsFor("operation").at(-1)!.filters).toEqual({
      label: "sql_generation",
      phase: "Answering",
      agent_id: "NL2SQL_ABC",
    });
    expect(trendCalls.at(-1)!.filters).toEqual({
      label: "sql_generation",
      phase: "Answering",
      agent_id: "NL2SQL_ABC",
    });
  });

  it("reads its facet options unfiltered, so a choice never empties the list", () => {
    render(<UsageView />);
    fireEvent.click(screen.getByRole("button", { name: "Custom Filters" }));
    fireEvent.change(screen.getByLabelText("Filter by operation"), {
      target: { value: "sql_generation" },
    });

    // The facet reads pass no filters: narrowing by one facet must not remove
    // the other facets' options and trap the reader on an empty screen.
    expect(callsFor("label").at(-1)!.filters).toEqual({});
    expect(callsFor("phase").at(-1)!.filters).toEqual({});
  });

  it("offers a way out of a combination with nothing behind it", () => {
    emptyTotals = true;
    render(<UsageView />);
    fireEvent.click(screen.getByRole("button", { name: "Custom Filters" }));

    expect(
      screen.getByText("No usage matches these filters."),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Clear filters" }),
    ).toBeInTheDocument();
  });
});

/* ── the drawer ─────────────────────────────────────────────────────────── */

describe("the breakdown drawer", () => {
  it("opens from a metric card with that card's own filter", () => {
    render(<UsageView />);
    fireEvent.click(metricCard("Total Tokens"));

    const drawer = screen.getByRole("dialog");
    expect(drawer).toHaveTextContent("Total Tokens");
    expect(drawer).toHaveTextContent("openai/gpt-oss-120b");
    // Total tokens on the one model: 1,000,000.
    expect(drawer).toHaveTextContent("1.0M");
    // Cost is derived, not returned: 1,000,000 tokens at $0.0000038.
    expect(drawer).toHaveTextContent("$3.8000");
    expect(drawer).toHaveTextContent("at $0.0000038 / token");
  });

  it("reports the operations with no model instead of hiding them", () => {
    render(<UsageView />);
    fireEvent.click(metricCard("Database queries"));

    const drawer = screen.getByRole("dialog");
    expect(drawer).toHaveTextContent(
      /A further 10 operations ran without a model/,
    );
    // The service-card drawer carries the operation filter it was opened with.
    expect(callsFor("model,provider").at(-1)!.filters).toEqual({
      operation: "db_query",
    });
  });

  it("closes on Escape and on the close button", () => {
    render(<UsageView />);
    fireEvent.click(metricCard("Requests"));
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    fireEvent.click(metricCard("Requests"));
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
