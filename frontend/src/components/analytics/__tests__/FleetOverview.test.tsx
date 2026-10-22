import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import FleetOverview from "../FleetOverview";

const useAnalyticsOverview = vi.fn();
vi.mock("@/data/analyticsOverview", () => ({
  useAnalyticsOverview: (...a: unknown[]) => useAnalyticsOverview(...a),
}));

const useAgents = vi.fn(() => ({ agents: [], isLoading: false, error: null }));
vi.mock("@/data/useAgents", () => ({
  useAgents: () => useAgents(),
  useSharedAgents: () => ({ agents: [], isLoading: false, error: null }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/database-agent/analytics",
  useSearchParams: () => new URLSearchParams(),
}));

const ROW = {
  agent_id: "NL2SQL_ABC",
  owner_id: "me@example.com",
  name: null,
  total_queries: 73,
  unique_users: 5,
  answered: 61,
  unanswered: 12,
  success_rate: 83.6,
  failed_api_requests: 0,
  avg_ms: 6495,
  p95_ms: 10045,
  total_tokens: 529338,
  total_cost: 0.185843,
  avg_cost_per_query: 0.002546,
  cost_complete: true,
  top_failure_category: "sql_error",
};

const answer = (over: Record<string, unknown> = {}) => ({
  data: {
    total_agents: 1,
    summary: { total_queries: 73, total_cost: 0.1858, cost_complete: true },
    agents: [ROW],
    ...over,
  },
  isLoading: false,
  isError: false,
  isFetching: false,
  error: null,
});

describe("FleetOverview", () => {
  beforeEach(() => {
    useAnalyticsOverview.mockReset();
    useAgents.mockReturnValue({ agents: [], isLoading: false, error: null });
  });

  it("renders one row per agent with its numbers", () => {
    useAnalyticsOverview.mockReturnValue(answer());
    render(<FleetOverview />);
    expect(screen.getByText("All agents")).toBeInTheDocument();
    expect(screen.getByText("83.6%")).toBeInTheDocument();
    expect(screen.getByText("sql_error")).toBeInTheDocument();
  });

  /**
   * Rows are keyed by the NL2SQL `agent_id`; this product's URLs are keyed by
   * the agent record whose `service_ref` that is. Link with the wrong one and
   * the page it opens cannot resolve the agent.
   */
  it("links a row through the agent record that owns the service id", () => {
    useAnalyticsOverview.mockReturnValue(answer());
    useAgents.mockReturnValue({
      agents: [{ agent_id: "AGENT_1", service_ref: "NL2SQL_ABC" }],
      isLoading: false,
      error: null,
    } as never);
    render(<FleetOverview />);
    expect(screen.getByRole("link", { name: /NL2SQL_ABC/ })).toHaveAttribute(
      "href",
      "/database-agent/analytics?agentId=AGENT_1",
    );
  });

  it("leaves a row unlinked when no agent record claims its service id", () => {
    useAnalyticsOverview.mockReturnValue(answer());
    render(<FleetOverview />);
    expect(screen.queryByRole("link", { name: /NL2SQL_ABC/ })).toBeNull();
    expect(screen.getByText("NL2SQL_ABC")).toBeInTheDocument();
  });

  it("warns when the window's costs are still a lower bound", () => {
    useAnalyticsOverview.mockReturnValue(
      answer({
        summary: { total_queries: 73, total_cost: 0.1, cost_complete: false },
      }),
    );
    render(<FleetOverview />);
    expect(screen.getByText(/still unpriced/)).toBeInTheDocument();
  });

  it("falls back to the picker only when nothing has been recorded", () => {
    useAnalyticsOverview.mockReturnValue(
      answer({ total_agents: 0, agents: [] }),
    );
    render(<FleetOverview fallback={<div>pick an agent</div>} />);
    expect(screen.getByText("pick an agent")).toBeInTheDocument();
  });
});
