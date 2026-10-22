import { describeAuthed } from "../../support/gate";
import { API, ROUTES } from "../../support/routes";

/**
 * Home — the agent list, its filters, the two workspace cards, and the New
 * agent wizard.
 *
 * The wizard is exercised up to (not through) provisioning: creating an agent
 * would leave a real agent and a real database link behind on every run.
 */
describeAuthed("Database Agent · Home", () => {
  beforeEach(() => {
    cy.intercept("GET", API.agents).as("agents");
    cy.intercept("GET", API.sharedAgents).as("shared");
    cy.visitApp(ROUTES.home);
    cy.wait("@agents");
  });

  it("renders the page header and both workspace cards", () => {
    cy.get("main").contains("h1", "Your database agents").should("be.visible");
    cy.contains("Usage & Limits").should("be.visible");
    cy.contains("Total Tokens").should("be.visible");
    cy.contains("Input Tokens").should("be.visible");
    cy.contains("Output Tokens").should("be.visible");
    cy.contains("Add Credentials").should("be.visible");
  });

  it("opens Usage from the Usage & Limits card", () => {
    cy.contains("Usage & Limits").click();
    cy.location("pathname").should("contain", "/usage");
    cy.contains("Token consumption across every NL2SQL agent").should(
      "be.visible",
    );
  });

  it("opens the Credentials screen from the card, and the form on it", () => {
    // The card is a link: the keys have their own screen, and the add form is a
    // dialog on that screen rather than one popped over Home.
    cy.contains("a", "Add Credentials").click();
    cy.location("pathname").should(
      "match",
      /\/database-agent\/credentials\/?$/,
    );
    cy.get("main").contains("Configured Providers").should("be.visible");

    cy.contains("button", "Add New Credentials").click();
    cy.dialog().within(() => {
      cy.contains("Add New Credential").should("be.visible");
      cy.get("#credential-provider").should("exist");
      cy.get("#credential-api-key").should("exist");
      cy.contains("button", "Add Credential").should("be.visible");
    });
  });

  it("switches between My Agents and Shared With Me", () => {
    cy.get('[role="tablist"][aria-label="Agent ownership"]').should("exist");

    cy.tab("Shared With Me");
    cy.get('[role="tab"][aria-selected="true"]').should(
      "contain.text",
      "Shared With Me",
    );
    // The owner filter only exists on the shared tab.
    cy.get('select[aria-label="Filter by owner"]').should("exist");

    cy.tab("My Agents");
    cy.get('[role="tab"][aria-selected="true"]').should(
      "contain.text",
      "My Agents",
    );
    cy.get('select[aria-label="Filter by owner"]').should("not.exist");
  });

  it("opens a shared agent by clicking its card", () => {
    cy.tab("Shared With Me");
    cy.wait("@shared");

    cy.get("body").then(($body) => {
      if (!$body.find('[aria-label^="Open "]').length) {
        cy.log("Nobody has shared an agent with this account.");
        return;
      }

      // A shared agent opens the way an owned one does — the whole card, not
      // only a small ghost button inside it.
      cy.get('[aria-label^="Open "]').first().click();
      cy.location("pathname").should("contain", "/conversations");
      cy.location("search").should("match", /agentId=.+/);
      // And it really resolves: the shell keeps its rail and names the agent.
      cy.get('aside[aria-label="Main navigation"]', { timeout: 60000 }).should(
        "be.visible",
      );
      cy.contains("h1", "Conversations").should("be.visible");
    });
  });

  it("counts what is shown against what exists, and search narrows it", () => {
    cy.contains(/Showing \d+ of \d+/).should("be.visible");

    cy.get('input[aria-label="Search agents"]').type(
      "zzz-no-agent-matches-this",
    );
    cy.contains("Showing 0 of").should("be.visible");
    cy.contains("No agents match").should("be.visible");

    cy.get('button[aria-label="Clear search"]').click();
    cy.get('input[aria-label="Search agents"]').should("have.value", "");
    cy.contains(/Showing \d+ of \d+/).should("be.visible");
  });

  it("gives each agent card the four row actions and opens Settings from one", () => {
    cy.get('[aria-label^="Settings for "]').should("exist");
    cy.get('[aria-label^="Analytics for "]').should("exist");
    cy.get('[aria-label^="Share "]').should("exist");
    cy.get('[aria-label^="Delete "]').should("exist");

    cy.get('[aria-label^="Settings for "]').first().click();
    cy.location("pathname").should("contain", "/settings");
    // The row action carries the card's own agent, not a guessed one.
    cy.location("search").should("match", /agentId=.+/);
  });

  it("asks before deleting an agent, and cancelling changes nothing", () => {
    cy.get('[aria-label^="Delete "]').first().click();
    cy.dialog().within(() => {
      cy.contains(/^Delete .+\?$/).should("be.visible");
      cy.contains("The databases themselves are untouched.").should(
        "be.visible",
      );
      cy.contains("button", "Cancel").click();
    });
    cy.get('[role="dialog"]').should("not.exist");
    cy.contains(/Showing \d+ of \d+/).should("be.visible");
  });

  describe("New agent wizard", () => {
    beforeEach(() => {
      cy.contains("button", "New agent").first().click();
      cy.dialog().should("contain.text", "New database agent");
    });

    it("walks step 1 to step 2 and offers all three ways to add a database", () => {
      cy.dialog().within(() => {
        cy.get("#wzName").type("Cypress smoke agent");
        cy.contains("button", "Next — connect a database").click();

        cy.get('[role="tablist"][aria-label="How to add the database"]').within(
          () => {
            cy.contains("Enter credentials").should("be.visible");
            cy.contains("Import from a file").should("be.visible");
            cy.contains("Discover on RDS").should("be.visible");
          },
        );

        // Manual is the default mode, with the full connection form.
        cy.get("#wzEngine").should("have.value", "postgresql");
        cy.get("#wzPort").should("have.value", "5432");
        cy.get("#wzHost").should("exist");
        cy.get("#wzDb").should("exist");
        cy.get("#wzUser").should("exist");
        cy.get("#wzPass").should("exist");
      });
    });

    it("moves the port with the engine", () => {
      cy.dialog().within(() => {
        cy.get("#wzName").type("Cypress smoke agent");
        cy.contains("button", "Next — connect a database").click();
        cy.get("#wzEngine").select("mysql");
        cy.get("#wzPort").should("have.value", "3306");
        cy.get("#wzEngine").select("mssql");
        cy.get("#wzPort").should("have.value", "1433");
      });
    });

    it("names the missing fields instead of provisioning a half-filled agent", () => {
      cy.dialog().within(() => {
        cy.get("#wzName").type("Cypress smoke agent");
        cy.contains("button", "Next — connect a database").click();
        cy.contains("button", "Test & create agent").click();
        cy.contains("Still needed:")
          .should("be.visible")
          .and("contain.text", "Host")
          .and("contain.text", "Database name")
          .and("contain.text", "Username")
          .and("contain.text", "Password");
      });
      // Nothing was created — the wizard is still on step 2.
      cy.dialog().contains("Test & create agent").should("be.visible");
    });

    it("switches to the file importer and loads its sample rows", () => {
      cy.dialog().within(() => {
        cy.get("#wzName").type("Cypress smoke agent");
        cy.contains("button", "Next — connect a database").click();
        cy.contains('[role="tab"]', "Import from a file").click();
        cy.contains("button", "Use this sample").click();
        cy.get("#wzPaste").invoke("val").should("have.length.greaterThan", 10);
      });
    });

    it("switches to RDS discovery and requires a host before fetching", () => {
      cy.dialog().within(() => {
        cy.get("#wzName").type("Cypress smoke agent");
        cy.contains("button", "Next — connect a database").click();
        cy.contains('[role="tab"]', "Discover on RDS").click();
        cy.get("#wzRHost").should("be.visible");
        cy.get("#wzREngine").should("have.value", "postgresql");
        cy.contains("button", "Fetch databases on this host").should(
          "be.visible",
        );
      });
    });

    it("closes without creating anything", () => {
      cy.dialog().contains("button", "Cancel").click();
      cy.get('[role="dialog"]').should("not.exist");
      cy.contains(/Showing \d+ of \d+/).should("be.visible");
    });
  });
});
