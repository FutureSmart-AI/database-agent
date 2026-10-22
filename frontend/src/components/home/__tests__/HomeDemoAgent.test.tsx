import type { ReactNode } from "react";

import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { toAgent } from "@/data/agents";
import { ToastProvider } from "@/platform/components/ToastContext";

import HomeView from "../HomeView";

/**
 * The shared example agent.
 *
 * The service lists one example agent first in every caller's `owned_agents`,
 * flagged `is_demo`, with somebody else's `owner_id` and `role: "viewer"`. My
 * Agents keeps it by that flag alone — any other non-owned row stays out — and
 * offers chat but none of the owner's actions, since deleting the one row
 * removes it for every user.
 */

const agents = [
  toAgent({
    agent_id: "demo-agent",
    agent_name: "SaaS Benchmark",
    owner_id: "someone-else@example.com",
    role: "viewer",
    is_demo: true,
  }),
  toAgent({ agent_id: "mine", agent_name: "My Agent", role: "owner" }),
  toAgent({
    agent_id: "not-mine",
    agent_name: "Someone Else's Agent",
    owner_id: "someone-else@example.com",
    role: "viewer",
  }),
];

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/database-agent",
}));

vi.mock("@/data/useAgents", () => ({
  useAgents: () => ({ agents, isLoading: false, error: null }),
  useSharedAgents: () => ({ agents: [], isLoading: false, error: null }),
}));
vi.mock("@/data/usage", () => ({ useUsageByAgent: () => ({ data: {} }) }));
vi.mock("@/data/mutations", () => ({
  useAgentMutations: () => ({
    remove: { mutateAsync: vi.fn(), isPending: false },
  }),
}));
vi.mock("@/lib/fonts", () => ({ NL2SQL_FONT_CLASS: "font-test" }));

const wrapped = (node: ReactNode) =>
  render(<ToastProvider>{node}</ToastProvider>);

describe("Home — shared example agent", () => {
  it("lists the example agent under My Agents, but no other non-owned row", () => {
    wrapped(<HomeView />);

    expect(
      screen.getByRole("button", { name: "Open SaaS Benchmark" }),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Open My Agent" })).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "Open Someone Else's Agent" }),
    ).toBeNull();
  });

  it("badges it as an example and offers none of the owner's actions", () => {
    wrapped(<HomeView />);

    const card = within(
      screen.getByRole("button", { name: "Open SaaS Benchmark" }),
    );
    expect(card.getByText("Example")).toBeTruthy();
    expect(card.queryByText("viewer")).toBeNull();
    expect(card.queryByRole("button", { name: /^Settings for/ })).toBeNull();
    expect(card.queryByRole("button", { name: /^Share / })).toBeNull();
    expect(card.queryByRole("button", { name: /^Delete / })).toBeNull();
  });

  it("leaves the owner's actions on the caller's own agent", () => {
    wrapped(<HomeView />);

    const card = within(screen.getByRole("button", { name: "Open My Agent" }));
    expect(card.getByRole("button", { name: "Settings for My Agent" }));
    expect(card.getByRole("button", { name: "Share My Agent" }));
    expect(card.getByRole("button", { name: "Delete My Agent" }));
  });
});
