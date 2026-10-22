import { describeAuthed } from "../../support/gate";
import { AGENT_SCOPED, API, ROUTES } from "../../support/routes";

/**
 * Every agent-scoped route reached without `?agentId=` must ask which agent is
 * meant rather than quietly opening the first one — the regression `AgentScope`
 * exists to prevent.
 */
describeAuthed("Database Agent · agent picker", () => {
  AGENT_SCOPED.forEach(({ route, title }) => {
    it(`asks which agent to open on ${title}`, () => {
      cy.intercept("GET", API.agents).as("agents");
      cy.visitApp(route);
      cy.wait("@agents");

      cy.get("main").contains("h1", "Select an agent").should("be.visible");
      // The shell has no agent, so it has no rail and no agent chip.
      cy.get('aside[aria-label="Main navigation"]').should("not.exist");
    });
  });

  it("opens the picked agent and keeps the route it was reached from", () => {
    cy.intercept("GET", API.agents).as("agents");
    cy.intercept("GET", API.databases).as("databases");
    cy.visitApp(ROUTES.analytics);
    cy.wait("@agents");

    cy.get("main").contains("h1", "Select an agent").should("be.visible");
    cy.get("main").contains("database").should("be.visible");

    cy.get("main").find("button").first().click();

    cy.location("pathname").should("contain", "/analytics");
    cy.location("search").should("match", /agentId=.+/);
    cy.get('aside[aria-label="Main navigation"]', { timeout: 60000 }).should(
      "be.visible",
    );
  });

  it("labels every choice with its database count and status", () => {
    cy.intercept("GET", API.agents).as("agents");
    cy.visitApp(ROUTES.settings);
    cy.wait("@agents");

    cy.get("main")
      .contains(/\d+ databases? connected/)
      .should("be.visible");
    cy.get("main")
      .contains(/^(Active|Paused)$/)
      .should("be.visible");
  });
});
