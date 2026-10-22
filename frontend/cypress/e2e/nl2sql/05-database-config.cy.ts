import { describeAuthed } from "../../support/gate";
import { API, ROUTES } from "../../support/routes";

/**
 * Settings → Databases → Configure: the three tabs that decide what the agent
 * is allowed to read and what it is shown when it writes SQL.
 *
 * Every assertion is on the panel's own behaviour — the draft it edits, the
 * confirmations it puts in front of destructive actions, the JSON importer. The
 * one write performed is a table visibility toggle, flipped back in the same
 * test.
 *
 * A database that cannot be reached renders a tab-free panel by design, so the
 * suite configures the first *reachable* row and reports the skip rather than
 * asserting against a panel that was never meant to be there.
 */
describeAuthed("Database Agent · database configuration panel", () => {
  /**
   * Opens Configure on the first database whose connection is up.
   *
   * An agent whose every database is refused renders a tab-free panel by
   * design, so there is nothing here to assert against. That is the state of
   * the workspace, not a defect, so the suite skips and says which agent to pin
   * instead of reporting a failure nobody can fix in the code.
   */
  const openConfigurePanel = (context: Mocha.Context) => {
    cy.get("main")
      .find("button")
      .filter(':contains("Configure")')
      .then(($buttons) => {
        const reachable = $buttons.toArray().filter((button) => {
          const row = button.closest("div.flex.flex-wrap");
          return !row?.textContent?.includes("Connection failed");
        });
        if (!reachable.length) {
          cy.log(
            "Every database on this agent is unreachable — the configuration " +
              "panel has no tabs to exercise. Pin a healthy agent with " +
              "CYPRESS_NL2SQL_AGENT_ID=<agent_id>.",
          );
          context.skip();
          return;
        }
        cy.wrap(reachable[0]).click();
        cy.contains("Configure —").should("be.visible");
      });
  };

  const configTab = (label: string) =>
    cy
      .get('[role="tablist"][aria-label="Database configuration"]')
      .contains(label)
      .click();

  beforeEach(function () {
    cy.intercept("GET", API.databases).as("databases");
    cy.intercept("GET", API.tables).as("tables");
    cy.intercept("GET", API.fewShot).as("fewShot");

    cy.visitAgent(ROUTES.settings);
    cy.wait("@databases");
    openConfigurePanel(this);
  });

  it("offers the three configuration tabs", () => {
    cy.get('[role="tablist"][aria-label="Database configuration"]').within(
      () => {
        cy.contains("Description").should("be.visible");
        cy.contains("Tables & visibility").should("be.visible");
        cy.contains("Few-shot examples").should("be.visible");
      },
    );
  });

  it("shows the description editor with its generate affordance", () => {
    cy.contains("Auto-generate description").should("be.visible");
    cy.contains("button", "Generate").should("be.visible");
    cy.get('textarea[id^="desc-"]').should("exist");
    cy.contains("button", "Save description").should("be.visible");
  });

  it("edits the description as a draft, and closing throws the draft away", function () {
    cy.get('textarea[id^="desc-"]')
      .invoke("val")
      .then((original) => {
        cy.get('textarea[id^="desc-"]').type(" — cypress draft", { delay: 0 });
        cy.get('textarea[id^="desc-"]').should(
          "have.value",
          `${original} — cypress draft`,
        );

        cy.contains("button", "Close").click();
        openConfigurePanel(this);
        cy.get('textarea[id^="desc-"]').should("have.value", original);
      });
  });

  describe("Tables & visibility", () => {
    beforeEach(() => {
      configTab("Tables & visibility");
      cy.wait("@tables");
      cy.get('input[type="checkbox"][aria-label="Select every table"]').should(
        "exist",
      );
    });

    it("lists the tables with their columns, description and visibility", () => {
      cy.get("main").contains("th", "Table").should("be.visible");
      cy.get("main").contains("th", "Visibility").should("be.visible");
      cy.get("main")
        .contains(/\d+ columns/)
        .should("be.visible");
      cy.get('input[aria-label^="Description for "]').should("exist");
      cy.get("main")
        .contains("button", /^(Included|Excluded)$/)
        .should("be.visible");
    });

    it("toggles one table's visibility and puts it back", () => {
      cy.get("main")
        .find("button")
        .filter(':contains("Included"), :contains("Excluded")')
        .first()
        .then(($toggle) => {
          const before = $toggle.text().trim();
          const after = before === "Included" ? "Excluded" : "Included";

          cy.wrap($toggle).click();
          cy.wrap($toggle).should("contain.text", after);
          cy.wrap($toggle).click();
          cy.wrap($toggle).should("contain.text", before);
        });
    });

    it("selects every table and offers the bulk actions", () => {
      cy.get('input[type="checkbox"][aria-label="Select every table"]').check();
      cy.contains(/\d+ tables? selected/).should("be.visible");
      cy.contains("button", "Regenerate selected").should("be.visible");
      cy.contains("button", "Delete descriptions").should("be.visible");
      cy.contains("button", "Deselect all").click();
      cy.contains(/\d+ tables? selected/).should("not.exist");
    });

    it("asks before regenerating every description, and cancelling stops it", () => {
      cy.contains("button", "Regenerate all").click();
      cy.dialog().within(() => {
        cy.contains("Regenerate every description?").should("be.visible");
        cy.contains("This cannot be undone.").should("be.visible");
        cy.contains("button", "Cancel").click();
      });
      cy.get('[role="dialog"]').should("not.exist");
    });

    it("asks before clearing the selected descriptions", () => {
      cy.get('input[type="checkbox"][aria-label="Select every table"]').check();
      cy.contains("button", "Delete descriptions").click();
      cy.dialog().within(() => {
        cy.contains(/^Delete \d+ descriptions?\?$/).should("be.visible");
        cy.contains("The tables themselves stay listed").should("be.visible");
        cy.contains("button", "Cancel").click();
      });
      cy.get('[role="dialog"]').should("not.exist");
      cy.contains("button", "Deselect all").click();
    });

    it("applies pasted JSON to the matching table only, as a draft", function () {
      const marker = `cypress import ${Date.now()}`;

      cy.get('input[aria-label^="Description for "]')
        .first()
        .invoke("attr", "aria-label")
        .then((label) => {
          const tableName = (label ?? "").replace(/^Description for /, "");

          cy.contains("button", "Paste JSON").click();
          cy.dialog().within(() => {
            cy.contains("Paste table descriptions").should("be.visible");
            cy.get('textarea[aria-label="JSON to import"]').type(
              JSON.stringify([{ table_name: tableName, description: marker }]),
              { parseSpecialCharSequences: false, delay: 0 },
            );
            cy.contains("button", "Apply").click();
          });

          cy.toast(/Applied 1 table description/);
          cy.get(`input[aria-label="Description for ${tableName}"]`).should(
            "have.value",
            marker,
          );
        });

      // Never saved: reopening reads the stored set again.
      cy.contains("button", "Close").click();
      openConfigurePanel(this);
      // No second `cy.wait("@tables")`: react-query already holds this
      // database's tables, so reopening the panel re-seeds the draft from the
      // cache without asking the service again.
      configTab("Tables & visibility");
      cy.get('input[aria-label^="Description for "]')
        .first()
        .should("not.have.value", marker);
    });

    it("rejects a paste that is not valid JSON", () => {
      cy.contains("button", "Paste JSON").click();
      cy.dialog().within(() => {
        cy.get('textarea[aria-label="JSON to import"]').type("not json", {
          delay: 0,
        });
        cy.contains("button", "Apply").click();
        // The parser's own message, whatever the engine words it as.
        cy.contains(/JSON|Unexpected/i).should("be.visible");
        cy.contains("button", "Cancel").click();
      });
      cy.get('[role="dialog"]').should("not.exist");
    });

    it("offers downloadable CSV and JSON samples", () => {
      cy.get('a[href="/templates/nl2sql/table-descriptions.csv"]').should(
        "exist",
      );
      cy.get('a[href="/templates/nl2sql/table-descriptions.json"]').should(
        "exist",
      );
    });
  });

  describe("Few-shot examples", () => {
    beforeEach(() => {
      configTab("Few-shot examples");
      cy.wait("@fewShot");
      cy.contains("These examples belong to").should("be.visible");
    });

    it("scopes the examples to this database and offers every entry point", () => {
      // The toolbar sits under a long example list on a busy database, and
      // Cypress only auto-scrolls for actions, not for assertions.
      cy.contains("button", "Add example")
        .scrollIntoView()
        .should("be.visible");
      cy.contains("button", "Paste JSON").should("be.visible");
      cy.get('a[href="/templates/nl2sql/few-shot-examples.csv"]').should(
        "exist",
      );
      cy.get('a[href="/templates/nl2sql/few-shot-examples.json"]').should(
        "exist",
      );
    });

    it("adds a blank row to the draft and removes it again", () => {
      cy.get("body").then(($body) => {
        const before = $body.find(
          'input[aria-label^="Question for example "]',
        ).length;

        cy.contains("button", "Add example").click();
        cy.get('input[aria-label^="Question for example "]').should(
          "have.length",
          before + 1,
        );
        cy.get('input[aria-label^="Question for example "]')
          .last()
          .should("have.value", "");

        // A row that was never stored is dropped locally, with no delete call.
        cy.get('button[aria-label="Remove example"]').last().click();
        if (before === 0) {
          cy.contains("No examples yet").should("be.visible");
        } else {
          cy.get('input[aria-label^="Question for example "]').should(
            "have.length",
            before,
          );
        }
      });
    });

    it("appends pasted JSON examples to the draft, and Close discards them", function () {
      const question = `cypress question ${Date.now()}`;

      cy.contains("button", "Paste JSON").click();
      cy.dialog().within(() => {
        cy.contains("Paste few-shot examples").should("be.visible");
        cy.get('textarea[aria-label="JSON to import"]').type(
          JSON.stringify([{ natural_query: question, sql_query: "SELECT 1" }]),
          { parseSpecialCharSequences: false, delay: 0 },
        );
        cy.contains("button", "Apply").click();
      });

      cy.toast(/Added 1 example/);
      cy.get(`input[value="${question}"]`).should("exist");

      cy.contains("button", "Close").click();
      openConfigurePanel(this);
      // Served from the query cache on reopen — see the note above.
      configTab("Few-shot examples");
      cy.contains("These examples belong to").should("be.visible");
      cy.get(`input[value="${question}"]`).should("not.exist");
    });

    it("says each pasted row needs a question and its SQL", () => {
      cy.contains("button", "Paste JSON").click();
      cy.dialog().within(() => {
        cy.get('textarea[aria-label="JSON to import"]').type(
          JSON.stringify([{ natural_query: "only a question" }]),
          { parseSpecialCharSequences: false, delay: 0 },
        );
        cy.contains("button", "Apply").click();
        cy.contains("Each row needs a question and its SQL.").should(
          "be.visible",
        );
        cy.contains("button", "Cancel").click();
      });
      cy.get('[role="dialog"]').should("not.exist");
    });
  });
});
