import { describeAuthed } from "../../support/gate";
import { API, ROUTES } from "../../support/routes";

/**
 * Usage & Limits — workspace-wide consumption, and the ceilings behind it.
 * Reached from Home rather than the rail, so it keeps its own way back.
 *
 * The screen reads four NL2SQL routes and the API contract asks callers not to
 * re-derive what they resolve, so what is asserted here is mostly what is NOT
 * drawn: no bar on a limit nobody enforces, no Service breakdown and no Hourly
 * granularity (both 422 at the service), and no figure that disagrees with the
 * one beside it.
 */
const rail = (label: string) =>
  cy.get('nav[aria-label="Usage sections"]').contains("button", label).click();

describeAuthed("Database Agent · Usage", () => {
  beforeEach(() => {
    cy.intercept("GET", API.usageAggregate).as("usageAggregate");
    cy.intercept("GET", API.ownerLimits).as("ownerLimits");
    cy.visitApp(ROUTES.usage);
    cy.get("main")
      .contains("h1", "Account Overview", { timeout: 60000 })
      .should("be.visible");
  });

  it("is workspace-level: no rail, and the topbar says so", () => {
    cy.get('aside[aria-label="Main navigation"]').should("not.exist");
    cy.get("header").contains("across all agents").should("be.visible");
    cy.contains("a", "Back to Home").should("be.visible");
  });

  it("offers its four sections", () => {
    cy.get('nav[aria-label="Usage sections"]').within(() => {
      ["Overview", "Limits", "Agents", "Custom Filters"].forEach((label) => {
        cy.contains("button", label).should("be.visible");
      });
    });
  });

  it("shows the cost as its own arithmetic, priced at the workspace rate", () => {
    cy.wait("@usageAggregate");
    // Total is platform + own keys, added in front of the reader, because that
    // sum IS the total — there is no separate total call to disagree with it.
    cy.get("main").contains("Total estimated cost").should("be.visible");
    cy.get("main").contains("Platform").should("be.visible");
    cy.get("main").contains("Your own keys").should("be.visible");
    cy.get("main")
      .contains(/per token/)
      .should("be.visible");
    ["Total Tokens", "Input Tokens", "Output Tokens", "Requests"].forEach(
      (card) => cy.get("main").contains(card).should("be.visible"),
    );
  });

  it("offers only the buckets the trend endpoint accepts", () => {
    // `/v1/trend` buckets day, week or month and 422s on anything else.
    cy.get('select[aria-label="Trend granularity"]')
      .find("option")
      .should(($options) => {
        expect([...$options].map((o) => o.textContent?.trim())).to.deep.equal([
          "Daily",
          "Weekly",
          "Monthly",
        ]);
      });
  });

  it("draws a bar only where a ceiling actually applies", () => {
    rail("Limits");
    cy.wait("@ownerLimits");
    cy.get("main").contains("Your plan").should("be.visible");

    // Server-driven rows: the labels, notes and ceilings are the service's.
    cy.get("main").contains("Chat requests per day").should("be.visible");

    // `limit: null` states the ceiling in words and draws no bar; a lifted
    // limit does the same. A bar against a ceiling nobody is enforcing is a lie
    // the reader can act on.
    cy.get("main")
      .contains("Databases on a single agent")
      .closest("div")
      .parent()
      .within(() => {
        cy.contains("no limit").should("be.visible");
        cy.get('[role="img"]').should("not.exist");
      });
  });

  it("fixes both controls on Limits, because neither applies to a ceiling", () => {
    rail("Limits");
    // A limit counts every request whichever key paid for it, and its window is
    // fixed in `billing_window`.
    cy.get('select[aria-label="Consumption source"]').should("be.disabled");
    cy.get('select[aria-label="Usage period"]').should("be.disabled");
    cy.get("main")
      .contains("The consumption-source filter does not apply")
      .should("be.visible");
  });

  it("lists usage per agent with every column", () => {
    rail("Agents");
    [
      "Agent",
      "Agent ID",
      "Requests",
      "Input Tokens",
      "Output Tokens",
      "Total Tokens",
      "Cost",
    ].forEach((head) => {
      cy.get("main").contains("th", head).should("be.visible");
    });
  });

  it("narrows by agent, operation and functional label — and offers no service facet", () => {
    rail("Custom Filters");
    cy.get('select[aria-label="Filter by agent"]').should("exist");
    cy.get('select[aria-label="Filter by operation"]').should("exist");
    cy.get('select[aria-label="Filter by functional label"]').should("exist");
    // `group_by=service_type` is a 422 — every row here is `nl2sql`, so the
    // grouping would always be one group and the service refuses it.
    cy.get("main").contains("Service").should("not.exist");
  });

  it("opens the model breakdown behind a figure", () => {
    cy.get('[title="Open the model breakdown for Total Tokens"]').click();
    cy.get('[role="dialog"]').within(() => {
      cy.contains("Breakdown by model and provider").should("be.visible");
      // Cost is derived from the token rate; no usage route returns one.
      cy.contains(/per token/).should("be.visible");
    });
  });

  it("goes back to Home", () => {
    cy.contains("a", "Back to Home").click();
    cy.location("pathname").should("match", /\/database-agent\/?$/);
    cy.get("main").contains("h1", "Your database agents").should("be.visible");
  });
});
