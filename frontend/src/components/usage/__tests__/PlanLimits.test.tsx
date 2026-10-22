import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import PlanLimits from "../PlanLimits";

/**
 * The four rules the API contract asks the Limits tab not to re-derive, each
 * asserted against a row the service really returns:
 *
 * · `lifted: true` → `percent: null` → **no bar**, and the ceiling still stated.
 * · `limit: null` → unlimited → no bar, never a 0% one.
 * · only `enforced: true` blocks — every other exceeded row is reporting.
 * · `percent` is the server's number, not a recomputation.
 */

const limits = {
  owner_id: "someone@example.com",
  tier: { name: "Trial", tier_type: "trial", is_default: true },
  billing_window: {
    days: 30,
    start: "2026-07-27T10:14:02+00:00",
    end: "2026-08-26T10:14:02+00:00",
  },
  own_credentials: ["groq"],
  token_rate_usd: 3.8e-6,
  groups: [
    {
      group: "Workspace",
      items: [
        {
          key: "agents",
          label: "Agents you can create",
          used: 35,
          limit: 10,
          unit: "agents",
          maximum: "10 agents on Trial",
          note: "Every database agent in this workspace counts, active or paused.",
          lifted_by: [],
          held: [],
          missing: [],
          lifted: false,
          percent: 100,
          raises: "plan",
          enforced: false,
        },
        {
          key: "databases_per_agent",
          label: "Databases on a single agent",
          used: 4,
          limit: null,
          unit: "databases",
          maximum: "No limit on Trial",
          note: "Your largest agent right now.",
          lifted: false,
          percent: null,
          raises: "plan",
          enforced: false,
        },
      ],
    },
    {
      group: "Requests, tokens and cost",
      items: [
        {
          key: "queries_per_day",
          label: "Chat requests per day",
          used: 20,
          limit: 20,
          unit: "requests",
          maximum: "20 requests per rolling 24 hours",
          note: "Questions asked across every agent.",
          lifted_by: ["google", "groq", "openai"],
          held: ["groq"],
          missing: ["google", "openai"],
          lifted: false,
          percent: 100,
          raises: "plan-or-own-keys",
          enforced: true,
        },
        {
          key: "tokens",
          label: "Total tokens this billing period",
          used: 400_000,
          limit: 600_000,
          unit: "tokens",
          maximum: "600,000 tokens per billing period on Trial",
          note: "Input plus output across every model that served a request.",
          lifted_by: ["groq"],
          held: ["groq"],
          missing: [],
          lifted: true,
          percent: null,
          raises: "own-keys",
          enforced: false,
        },
        {
          // The service sends this one's unit as "USD", uppercase.
          key: "cost",
          label: "Estimated cost this billing period",
          used: 0.0297122,
          limit: 3.8,
          unit: "USD",
          maximum:
            "$3.8000 per billing period — derived from the token ceiling",
          note: "An estimate, not a bill.",
          lifted: false,
          percent: 0.7819,
          raises: "plan",
          enforced: false,
        },
      ],
    },
  ],
  exceeded: ["agents", "queries_per_day"],
};

vi.mock("@/data/usage", () => ({
  useOwnerLimits: () => ({ data: limits, isLoading: false, error: null }),
}));

const bars = () => screen.queryAllByRole("img");

describe("PlanLimits", () => {
  it("draws a bar only for a limit that actually applies", () => {
    render(<PlanLimits />);

    // Five rows, three ceilings that apply: `agents` and `queries_per_day`.
    // `tokens` is lifted and `databases_per_agent` is uncapped — neither may be
    // drawn as a bar, because a bar against a ceiling nobody enforces is a lie
    // the reader can act on.
    expect(bars()).toHaveLength(3);
    expect(bars().map((bar) => bar.getAttribute("aria-label"))).toEqual([
      "35 of 10 agents used, 100%",
      "20 of 20 requests used, 100%",
      "$0.03 of $3.80 used, 1%",
    ]);
  });

  it("states the ceiling on a lifted limit and says it does not apply", () => {
    render(<PlanLimits />);

    expect(
      screen.getByText(
        /Maximum: 600,000 tokens per billing period on Trial — not applied to you\./,
      ),
    ).toBeInTheDocument();
    // `nfmt` compacts at ten thousand, as it does everywhere else on the screen.
    expect(screen.getByText("400.0K tokens · not capped")).toBeInTheDocument();
    expect(screen.getByText(/Lifted by your own Groq key/)).toBeInTheDocument();
  });

  it("does not print the currency twice on a money row", () => {
    render(<PlanLimits />);

    // The `$` already carries the currency, so the unit is dropped rather than
    // rendered as "$0.03 of $3.80 USD" — which is what shipped until it was
    // seen against the live response, where `unit` is "USD" and not "usd".
    expect(screen.getByText("$0.03 of $3.80")).toBeInTheDocument();
    expect(screen.queryByText(/USD/)).not.toBeInTheDocument();
  });

  it("says no limit rather than showing an empty allowance", () => {
    render(<PlanLimits />);

    expect(screen.getByText("4 databases · no limit")).toBeInTheDocument();
    expect(
      screen.getByText(/Maximum: No limit on Trial\./),
    ).toBeInTheDocument();
  });

  it("banners only the exceeded limit that blocks", () => {
    render(<PlanLimits />);

    // Both `agents` and `queries_per_day` are exceeded; only the enforced one
    // stops anything, so only it gets the outage banner.
    expect(
      screen.getByText("Chat requests per day reached"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Agents you can create reached"),
    ).not.toBeInTheDocument();

    // And the two exceeded rows are labelled differently for the same reason.
    expect(screen.getByText("Blocking")).toBeInTheDocument();
    expect(screen.getByText("No headroom")).toBeInTheDocument();
  });

  it("names both escape routes on a limit that either would move", () => {
    render(<PlanLimits />);

    expect(
      screen.getByText(
        /a higher tier lifts the ceiling, or your own Google and OpenAI keys removes it entirely/,
      ),
    ).toBeInTheDocument();
    // Both workspace rows have no own-key route (`missing: []`), and each says
    // so on its own row rather than once for the group.
    expect(
      screen.getAllByText(
        /Only a tier change raises this one — adding your own keys changes what you pay for, not this ceiling\./,
      ),
    ).toHaveLength(3);
  });

  it("reports the fixed billing window and that neither control applies", () => {
    render(<PlanLimits />);

    expect(
      screen.getByText(
        /Billing period · 27 Jul 2026 – 26 Aug 2026 \(30 days\)/,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /The consumption-source filter does not apply on this tab/,
      ),
    ).toBeInTheDocument();
    expect(screen.getByText(/Trial tier/)).toBeInTheDocument();
    expect(
      screen.getByText(/Using your own keys for Groq/),
    ).toBeInTheDocument();
  });
});
