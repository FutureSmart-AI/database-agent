import type { ReactNode } from "react";

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/platform/components/ToastContext";

import HomeView from "../HomeView";

/**
 * Home's credentials entry point.
 *
 * The design's home board has an "Add Credentials" card, and clicking it goes to
 * the credentials screen (`go('credentials')`) — the keys are a screen of their
 * own there, with its own back link, tiles and table. Adding and editing a key
 * is a dialog *on that screen*. Opening that dialog straight from home skips the
 * screen the design draws, so this pins the card to a link.
 */

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/database-agent",
}));

vi.mock("@/data/useAgents", () => ({
  useAgents: () => ({ agents: [], isLoading: false, error: null }),
  useSharedAgents: () => ({ agents: [], isLoading: false, error: null }),
}));
vi.mock("@/data/usage", () => ({ useUsageByAgent: () => ({ data: {} }) }));
vi.mock("@/data/mutations", () => ({
  useAgentMutations: () => ({
    remove: { mutateAsync: vi.fn(), isPending: false },
  }),
}));
vi.mock("@/lib/fonts", () => ({ NL2SQL_FONT_CLASS: "font-test" }));
const demo = vi.hoisted(() => ({
  allowance: {
    daily_limit: 5,
    daily_used: 1,
    daily_remaining: 4,
    daily_resets_at: null as string | null,
    total_limit: 20,
    total_used: 1,
    total_remaining: 19,
    budget_open: true,
  },
}));
vi.mock("@/data/demo", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/data/demo")>()),
  useDemoAllowance: () => ({ data: demo.allowance }),
}));

const wrapped = (node: ReactNode) =>
  render(<ToastProvider>{node}</ToastProvider>);

describe("Home — credentials entry point", () => {
  it("sends the Add Credentials card to the credentials screen", async () => {
    wrapped(<HomeView />);

    const card = screen.getByRole("link", { name: /Add Credentials/ });
    expect(card.getAttribute("href")).toBe("/database-agent/credentials");
  });

  it("carries no key form of its own — that lives on the credentials screen", () => {
    wrapped(<HomeView />);

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByLabelText(/API key/i)).toBeNull();
    expect(
      screen.queryByRole("button", { name: /Add Credential$/ }),
    ).toBeNull();
  });
});
