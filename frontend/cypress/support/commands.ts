import { API, ROUTES, type Route } from "./routes";

/**
 * Custom commands shared by the NL2SQL specs.
 *
 * The suite runs against the live backend through the dev proxy, so the two
 * things every agent-scoped spec needs are (a) a real agent id and (b) a way to
 * open a product route with that id attached. Both live here so no spec has to
 * hard-code a workspace's data.
 */

/** Resolved once per spec file, so only the first agent-scoped test pays for it. */
let resolvedAgentId: string | null = null;

declare global {
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace Cypress {
    interface Chainable {
      /**
       * The agent the agent-scoped specs open: `CYPRESS_NL2SQL_AGENT_ID` when
       * pinned, otherwise the first agent in the workspace that has the NL2SQL
       * service. Fails loudly rather than silently testing the wrong agent.
       */
      nl2sqlAgentId(): Chainable<string>;
      /** Opens a product route, with `?agentId=` when one is given. */
      visitApp(route: Route | string, agentId?: string): Chainable<AUTWindow>;
      /** Opens an agent-scoped route for the resolved agent. */
      visitAgent(route: Route | string): Chainable<string>;
      /** The product shell has painted: topbar brand plus the page heading. */
      shellReady(): Chainable<JQuery<HTMLElement>>;
      /** Clicks a `TabNav` / `role="tab"` entry by its visible label. */
      tab(label: string | RegExp): Chainable<JQuery<HTMLElement>>;
      /** The dialog currently open, by its accessible role. */
      dialog(): Chainable<JQuery<HTMLElement>>;
      /** Waits for a toast carrying `text` (the app toasts every mutation). */
      toast(text: string | RegExp): Chainable<JQuery<HTMLElement>>;
    }
  }
}

interface RegistryRow {
  agent_id: string;
  services?: Array<{ service_type: string; status?: string }>;
}

const firstNl2sql = (rows: RegistryRow[]): RegistryRow | undefined =>
  rows.find((row) =>
    row.services?.some((service) => service.service_type === "nl2sql"),
  );

Cypress.Commands.add("nl2sqlAgentId", () => {
  const pinned = (Cypress.env("NL2SQL_AGENT_ID") as string) || "";
  if (pinned) return cy.wrap(pinned, { log: false });
  if (resolvedAgentId) return cy.wrap(resolvedAgentId, { log: false });

  cy.intercept("GET", API.agents).as("resolveAgents");
  cy.intercept("GET", API.sharedAgents).as("resolveShared");
  cy.visit(ROUTES.home);

  return cy.wait(["@resolveAgents", "@resolveShared"]).then((interceptions) => {
    // Owned first, then shared: an account can perfectly well own nothing and
    // work entirely inside agents other people shared with it, and the suite
    // has to test what that account actually has.
    const [owned, shared] = interceptions.map(
      (interception) =>
        (interception.response?.body?.data ?? []) as RegistryRow[],
    );
    const match = firstNl2sql(owned) ?? firstNl2sql(shared);

    if (!match) {
      throw new Error(
        "No NL2SQL agent this account can reach — none owned, none shared. " +
          "Create one, or pin an agent with CYPRESS_NL2SQL_AGENT_ID=<agent_id>.",
      );
    }
    resolvedAgentId = match.agent_id;
    return cy.wrap(resolvedAgentId, { log: false });
  });
});

Cypress.Commands.add("visitApp", (route: string, agentId?: string) =>
  cy.visit(agentId ? `${route}?agentId=${agentId}` : route),
);

Cypress.Commands.add("visitAgent", (route: string) =>
  cy.nl2sqlAgentId().then((agentId) => {
    cy.visitApp(route, agentId);
    return cy.wrap(agentId, { log: false });
  }),
);

Cypress.Commands.add("shellReady", () => {
  // The brand link is in the fixed topbar of every product page and does not
  // depend on any request resolving, so it is the honest "the app mounted"
  // signal — page content is asserted per spec.
  cy.get("header").contains("FutureSmart").should("be.visible");
  return cy.get("main").should("exist");
});

Cypress.Commands.add("tab", (label: string | RegExp) =>
  cy.get('[role="tab"]').contains(label).click(),
);

Cypress.Commands.add("dialog", () =>
  cy.get('[role="dialog"]').filter(":visible").last(),
);

Cypress.Commands.add(
  "toast",
  (text: string | RegExp) =>
    cy
      .contains(text, { timeout: 30000 })
      .should("be.visible") as unknown as Cypress.Chainable<
      JQuery<HTMLElement>
    >,
);

export {};
