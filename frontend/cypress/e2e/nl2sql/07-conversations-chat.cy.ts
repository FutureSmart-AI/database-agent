import { describeAuthed } from "../../support/gate";
import { API, ROUTES } from "../../support/routes";

/**
 * Conversations — the agent UI's chat, mounted in this product.
 *
 * The "asks a question" test runs a real query against a real database and
 * costs tokens, so it is the one spec behind a second opt-in
 * (`CYPRESS_E2E_ASK=1`). Everything around it — the list, the tabs, the new
 * chat view, the read-only monitoring tabs, the sources panel on a stored
 * answer — runs on what the agent already has.
 */
const canAsk = Boolean(Cypress.env("E2E_ASK"));

describeAuthed("Database Agent · Conversations", () => {
  beforeEach(() => {
    cy.intercept("GET", API.databases).as("databases");
    cy.intercept("GET", API.agentConfig).as("agentConfig");
    cy.visitAgent(ROUTES.conversations);
    cy.contains("h1", "Conversations", { timeout: 60000 }).should("be.visible");
  });

  it("mounts the chat with its list and a New chat action", () => {
    cy.contains("button", "New chat").should("be.visible");

    // This product's own chat, not the dashboard's: the thread list is a
    // labelled complementary with a search box, and the owner-only monitoring
    // tabs are deliberately absent (see `constants.ts`).
    cy.get('[aria-label="Conversations"]').should("exist");
    cy.get('input[aria-label="Search conversations"]').should("be.visible");
    cy.contains('[role="tab"]', "Users").should("not.exist");
    cy.contains('[role="tab"]', "Widget").should("not.exist");
  });

  it("opens on the new-chat view with a usable composer", () => {
    cy.get('textarea[aria-label="Message"]').should("be.visible");
    cy.get('button[aria-label="Send message"]').should("exist");
    cy.contains("Ask a question about your data in plain English.").should(
      "be.visible",
    );
  });

  it("types into the composer and clears it again", () => {
    cy.get('textarea[aria-label="Message"]').type(
      "how many orders were placed last month?",
      { delay: 0 },
    );
    cy.get('textarea[aria-label="Message"]').should(
      "have.value",
      "how many orders were placed last month?",
    );
    cy.get('button[aria-label="Clear message"]').click();
    cy.get('textarea[aria-label="Message"]').should("have.value", "");
  });

  it("keeps the send button disabled until there is something to send", () => {
    cy.get('button[aria-label="Send message"]').should("be.disabled");
    cy.get('textarea[aria-label="Message"]').type("hello", { delay: 0 });
    cy.get('button[aria-label="Send message"]').should("not.be.disabled");
  });

  it("keeps the composer available because monitoring tabs are absent", () => {
    cy.contains('[role="tab"]', "Users").should("not.exist");
    cy.contains('[role="tab"]', "Widget").should("not.exist");
    cy.get('textarea[aria-label="Message"]').should("be.visible");
  });

  it("returns to a blank thread when New chat is pressed", () => {
    cy.contains("button", "New chat").click();
    cy.get('textarea[aria-label="Message"]')
      .should("be.visible")
      .and("have.value", "");
  });

  describe("a stored conversation", () => {
    it("opens one from the list and renders its turns", () => {
      // The list settles into either sessions or its own empty state; an agent
      // nobody has asked anything has nothing to open, and that is not a defect.
      cy.get("body", { timeout: 60000 }).should(($body) => {
        const settled =
          $body.find('li[role="button"]').length > 0 ||
          $body.text().includes("No conversations yet");
        expect(settled, "conversation list has settled").to.be.true;
      });

      cy.get("body").then(($body) => {
        if (!$body.find('li[role="button"]').length) {
          cy.log("No stored conversations on this agent — nothing to open.");
          return;
        }

        cy.get('li[role="button"]').first().click();
        // Either the stored turns render — an answer carries the result card
        // and the run log under it — or the app says the run never produced an
        // answer. Both are real, asserted states.
        cy.contains(/Full logs|This conversation has no saved answer\./, {
          timeout: 60000,
        }).should("be.visible");
      });
    });
  });

  (canAsk ? describe : describe.skip)("asking a question", () => {
    it("streams an answer, then shows the result card's tabs and the run log", () => {
      cy.intercept("POST", API.chat).as("ask");

      cy.contains("button", "New chat").click();
      cy.get('textarea[aria-label="Message"]').type(
        "how many rows are in the largest table?",
        { delay: 0 },
      );
      cy.get('button[aria-label="Send message"]').click();

      // The question lands in the thread straight away.
      cy.contains("how many rows are in the largest table?").should(
        "be.visible",
      );

      cy.wait("@ask", { timeout: 180000 })
        .its("response.statusCode")
        .should("eq", 200);

      // An answered question carries one card with a tab per reading of the
      // result. Query is there whenever the agent shows its SQL; Data whenever
      // rows came back.
      cy.contains('[role="tab"]', /Query|Data/, { timeout: 180000 }).should(
        "be.visible",
      );

      cy.get("body").then(($body) => {
        if ($body.find('[role="tab"]:contains("Data")').length) {
          cy.contains('[role="tab"]', "Data").click();
          cy.contains(/rows|Showing/).should("be.visible");
        }
        if ($body.find('[role="tab"]:contains("Query")').length) {
          cy.contains('[role="tab"]', "Query").click();
          cy.contains(/select/i).should("be.visible");
        }
        // Every chart carries the picker, so the reader can redraw the result
        // the service suggested one way as any other.
        if ($body.find('[role="tab"]:contains("Chart")').length) {
          cy.contains('[role="tab"]', "Chart").click();
          cy.get('[role="group"][aria-label="Chart type"]').should("exist");
          cy.get('button[aria-label="Pie chart"]').click();
          cy.contains("Shown as").should("be.visible");
        }
      });

      // What the run did in the background, folded under the answer.
      cy.contains("button", "Full logs").should("be.visible").click();
      cy.contains(/Wrote the query|Read the question|Ran the query/).should(
        "be.visible",
      );
    });
  });
});
