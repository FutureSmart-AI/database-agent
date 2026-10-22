import { describeAuthed } from "../../support/gate";
import { AGENT_SCOPED, API, ROUTES } from "../../support/routes";

/**
 * The product chrome: entry points, the five-item rail, the agent chip, and the
 * agent dashboard's own Database Agent page, which is a separate screen from
 * this one.
 *
 * Everything asserted here is chrome the app renders from its own route table,
 * so it holds for a workspace with one agent and for a workspace with fifty.
 *
 * Known layout quirk this suite has to work around: the rail is `fixed` from
 * `top: 0`, so its own header row — heading plus a "Collapse sidebar" button —
 * renders underneath the fixed topbar. The button is focusable but not
 * clickable. The floating handle on the rail's edge is the one people use, and
 * the one asserted below.
 */
describeAuthed("Database Agent · shell and navigation", () => {
  it("forwards the retired /nl2sql/dashboard URL to the product", () => {
    // The product dropped its `/dashboard` segment when the marketing page
    // above it went away. Old bookmarks keep working through a client-side hop,
    // which is all a static export can offer.
    cy.visit(ROUTES.legacyDashboard);
    cy.location("pathname", { timeout: 30000 }).should(
      "match",
      /\/database-agent\/?$/,
    );
    cy.shellReady();
  });

  it("shows Home without a rail — it is workspace-level, not agent-scoped", () => {
    cy.visitApp(ROUTES.home);
    cy.shellReady();
    cy.contains("h1", "Home").should("be.visible");
    cy.get('aside[aria-label="Main navigation"]').should("not.exist");
  });

  it("renders the five rail entries once an agent is open", () => {
    cy.visitAgent(ROUTES.settings);
    cy.get('aside[aria-label="Main navigation"]', { timeout: 60000 }).should(
      "be.visible",
    );

    const labels = ["Home", "Conversations", "Analytics", "Share", "Settings"];
    labels.forEach((label) => {
      cy.get('aside[aria-label="Main navigation"]')
        .contains(label)
        .should("be.visible");
    });

    // Batch Query Reports still answers on its own route, but it is no longer
    // one of the rail's destinations.
    cy.get('aside[aria-label="Main navigation"]')
      .contains("Batch Query Reports")
      .should("not.exist");

    // Settings is the page we are on, so its link is the current one.
    cy.get('aside[aria-label="Main navigation"] a[aria-current="page"]')
      .should("have.length", 1)
      .and("contain.text", "Settings");
  });

  it("keeps the agent in the URL when moving between rail entries", () => {
    cy.nl2sqlAgentId().then((agentId) => {
      cy.visitApp(ROUTES.settings, agentId);
      cy.get('aside[aria-label="Main navigation"]', { timeout: 60000 }).should(
        "be.visible",
      );

      cy.get('aside[aria-label="Main navigation"]')
        .contains("Analytics")
        .click();
      cy.location("pathname").should("contain", "/analytics");
      cy.location("search").should("contain", `agentId=${agentId}`);

      cy.get('aside[aria-label="Main navigation"]').contains("Share").click();
      cy.location("pathname").should("contain", "/share");
      cy.location("search").should("contain", `agentId=${agentId}`);

      // Home is workspace-level and deliberately drops the agent.
      cy.get('aside[aria-label="Main navigation"]').contains("Home").click();
      cy.location("pathname").should("match", /\/database-agent\/?$/);
      cy.location("search").should("not.contain", "agentId");
    });
  });

  it("names the open agent in the topbar chip with its database and table counts", () => {
    cy.intercept("GET", API.databases).as("databases");
    cy.visitAgent(ROUTES.settings);
    cy.wait("@databases");
    cy.get("header")
      .contains(/\d+ databases?\s·\s\d+ tables/)
      .should("be.visible");
  });

  it("collapses and expands the rail", () => {
    cy.visitAgent(ROUTES.settings);
    cy.get('aside[aria-label="Main navigation"]', { timeout: 60000 }).should(
      "be.visible",
    );

    // Two controls carry this label: the one in the rail's own header, and the
    // floating handle on its edge. The header one sits *behind* the fixed
    // topbar and cannot be clicked — see the note in the spec header — so the
    // reachable one is the last in the DOM.
    cy.get('button[aria-label="Collapse sidebar"]').last().click();
    cy.get('button[aria-label="Expand sidebar"]').should("exist");
    // Collapsed, the rail is icon-only: the labels go, the links stay.
    cy.get('aside[aria-label="Main navigation"] a').should("have.length", 5);

    cy.get('button[aria-label="Expand sidebar"]').last().click();
    cy.get('aside[aria-label="Main navigation"]')
      .contains("Conversations")
      .should("be.visible");
  });

  it("titles every agent-scoped page in the topbar", () => {
    cy.nl2sqlAgentId().then((agentId) => {
      AGENT_SCOPED.forEach(({ route, title }) => {
        cy.visitApp(route, agentId);
        cy.shellReady();
        // Analytics names the agent, so the title is a prefix there.
        cy.get("header h1", { timeout: 60000 }).should("contain.text", title);
      });
    });
  });

  it("offers a mobile navigation drawer on a narrow viewport", () => {
    cy.viewport(390, 844);
    cy.visitAgent(ROUTES.settings);
    cy.get('button[aria-label="Open navigation"]', { timeout: 60000 }).click();
    cy.get("#nl2sql-mobile-navigation")
      .should("be.visible")
      .within(() => {
        cy.contains("Conversations").should("be.visible");
        cy.contains("Settings").should("be.visible");
      });
    cy.get('button[aria-label="Close navigation"]').click();
    cy.get("#nl2sql-mobile-navigation").should("not.exist");
  });
});
