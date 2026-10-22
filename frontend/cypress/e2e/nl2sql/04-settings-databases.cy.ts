import { describeAuthed } from "../../support/gate";
import { API, ROUTES } from "../../support/routes";

/**
 * Settings → Databases: the connection list, the credentials modal (including
 * its standalone connection test), and the remove confirmation.
 *
 * Nothing here removes a database or overwrites a stored password. "Check all"
 * and "Test connection" are the two live calls the suite does make: both are
 * read-only probes the product runs on demand anyway.
 */
describeAuthed("Database Agent · Settings → Databases", () => {
  beforeEach(() => {
    cy.intercept("GET", API.databases).as("databases");
    cy.visitAgent(ROUTES.settings);
    cy.wait("@databases");
    cy.get("main").contains("h1", "Settings").should("be.visible");
  });

  it("opens on the Databases tab with the section's three controls", () => {
    cy.get('[role="tab"][aria-selected="true"]').should(
      "contain.text",
      "Databases",
    );
    cy.contains("Each database is queried on its own.").should("be.visible");
    cy.contains("button", "Check all").should("be.visible");
    cy.contains("button", "Add database").should("be.visible");
  });

  it("lists each database with its host, engine, status and table count", () => {
    cy.get("main").contains(/:\d+$/).should("be.visible");
    cy.get("main")
      .contains(/^\d+ tables?$/)
      .should("be.visible");
    cy.get("main")
      .contains(/Description set|Add description to activate|Connection failed/)
      .should("be.visible");
    cy.get('[role="switch"][aria-label^="Include "]').should("exist");
    cy.get('button:contains("Edit credentials")').should("exist");
    cy.get('button:contains("Configure")').should("exist");
  });

  it("checks every connection and reports the result", () => {
    cy.intercept("POST", API.databasesCheck).as("checkAll");
    cy.contains("button", "Check all").click();
    cy.wait("@checkAll").its("response.statusCode").should("be.oneOf", [200]);
    cy.toast(/database(s)? answered|could not be reached/);
  });

  describe("credentials modal", () => {
    it("opens the add form empty, with PostgreSQL and its default port", () => {
      cy.contains("button", "Add database").click();
      cy.dialog().within(() => {
        cy.contains("Add database").should("be.visible");
        cy.get("#credEngine").should("have.value", "postgresql");
        cy.get("#credPort").should("have.value", "5432");
        cy.get("#credHost").should("have.value", "");
        cy.get("#credDb").should("have.value", "");
        cy.get("#credUser").should("have.value", "");
        cy.get("#credPass").should("have.value", "");
        cy.contains("Use a read-only user").should("be.visible");
      });
    });

    it("moves the port with the engine", () => {
      cy.contains("button", "Add database").click();
      cy.dialog().within(() => {
        cy.get("#credEngine").select("mysql");
        cy.get("#credPort").should("have.value", "3306");
        cy.get("#credEngine").select("mssql");
        cy.get("#credPort").should("have.value", "1433");
      });
    });

    it("names the missing fields instead of saving a half-filled connection", () => {
      cy.contains("button", "Add database").click();
      cy.dialog().within(() => {
        cy.contains("button", "Add & test").click();
        cy.contains("Still needed:")
          .should("be.visible")
          .and("contain.text", "Database name")
          .and("contain.text", "Host")
          .and("contain.text", "Username")
          .and("contain.text", "Password");
      });
      // Still open: nothing was sent.
      cy.dialog().contains("button", "Add & test").should("be.visible");
    });

    it("refuses to test until the form is complete, then reports the attempt", () => {
      cy.contains("button", "Add database").click();
      cy.dialog().within(() => {
        cy.contains("button", "Test connection").click();
        cy.contains("Still needed:").should("be.visible");
      });

      cy.intercept("POST", API.databaseTest).as("testConnection");
      cy.dialog().within(() => {
        cy.get("#credHost").type("cypress.invalid.example.com");
        cy.get("#credDb").type("cypress_probe");
        cy.get("#credUser").type("cypress");
        cy.get("#credPass").type("cypress");
        cy.contains("button", "Test connection").click();
      });
      cy.wait("@testConnection");
      // A refused host is the expected answer — what matters is that the modal
      // reports it rather than swallowing it.
      cy.dialog()
        .contains(/Connection works|Could not connect/)
        .should("be.visible");
    });

    it("says a stored password has to be re-entered when editing", () => {
      cy.contains("button", "Edit credentials").first().click();
      cy.dialog().within(() => {
        cy.contains("Edit credentials —").should("be.visible");
        cy.contains("Saving tests the connection again").should("be.visible");
        cy.get("#credHost").invoke("val").should("not.be.empty");
        cy.get("#credPass").should("have.value", "");
        cy.contains("Stored encrypted and never returned").should("be.visible");
        cy.contains("button", "Save & test").should("be.visible");
        cy.contains("button", "Cancel").click();
      });
      cy.get('[role="dialog"]').should("not.exist");
    });
  });

  it("asks before removing a database, and cancelling leaves the list alone", () => {
    cy.get('button[aria-label^="Remove "]')
      .first()
      .then(($button) => {
        const label = $button.attr("aria-label") ?? "";
        const dbName = label.replace(/^Remove /, "");
        cy.wrap($button).click();
        cy.dialog().within(() => {
          cy.contains(`Remove ${dbName}?`).should("be.visible");
          cy.contains("the database itself is untouched").should("be.visible");
          cy.contains("button", "Cancel").click();
        });
        cy.get('[role="dialog"]').should("not.exist");
        cy.get('button[aria-label="Remove ' + dbName + '"]').should("exist");
      });
  });
});
