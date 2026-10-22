import { describeAuthed } from "../../support/gate";
import { API, ROUTES } from "../../support/routes";

/** The notice shown when the list request itself failed. */
const UNAVAILABLE = /Reports could not be loaded/;

/**
 * Batch Query Reports — the list, the create form and the run history.
 *
 * Reports come from the NL2SQL service's own agent-scoped routes
 * (`/nl2sql/api/v1/agents/{agent_id}/reports…`). The dashboard service's
 * `?agent_id=` routes are keyed by chat-registry ids and rejected an `NL2SQL_…`
 * agent, which is what used to leave this page saying reports were unavailable.
 *
 * Saving a report would start real queries against a real database on every
 * run, so the form is exercised through its validation and its group editor and
 * then cancelled. Opening an existing report's run history is read-only and is
 * covered when the agent has one.
 */
describeAuthed("Database Agent · Batch Query Reports", () => {
  beforeEach(() => {
    cy.intercept("GET", API.databases).as("databases");
    cy.intercept("GET", API.reports).as("reports");
    cy.intercept("GET", API.dashboardReports).as("dashboardReports");

    cy.visitAgent(ROUTES.reports);
    cy.get("main")
      .contains("h1", "Reports", { timeout: 60000 })
      .should("be.visible");
  });

  it("lists the reports, or says why there are none", () => {
    cy.contains("Batch query evaluations").should("be.visible");
    cy.contains("button", "New Report").should("be.visible");

    cy.get("main").should(($main) => {
      const text = $main.text();
      expect(
        text.includes("No reports yet") ||
          // A failed list still says so in the page's own words rather than
          // printing the backend's `detail`.
          UNAVAILABLE.test(text) ||
          /\d+ groups? ·/.test(text),
        "the list rendered its rows, its empty state, or the failure notice",
      ).to.be.true;
    });
    // Whatever the state, the caller's email and the agent id never appear.
    cy.get("main").should(($main) => {
      expect(
        /has no access to agent|NL2SQL_[0-9A-F]{8}/.test($main.text()),
        "no raw backend detail",
      ).to.be.false;
    });
  });

  it("reads the list from the NL2SQL service, never the dashboard's", () => {
    cy.wait("@reports")
      .its("request.url")
      .should("match", /\/nl2sql\/api\/v1\/agents\/[^/]+\/reports/);
    // The dashboard routes 403 for these ids; the page must not call them.
    cy.get("@dashboardReports.all").should("have.length", 0);
  });

  describe("create form", () => {
    beforeEach(() => {
      cy.contains("button", "New Report").click();
      cy.get("main").contains("h1", "Create Report").should("be.visible");
    });

    it("opens with one independent group holding one blank query", () => {
      cy.get("#repName").should("have.value", "");
      cy.get("#repSchedule").should("have.value", "none");
      cy.contains("Group 1").should("be.visible");
      cy.get('input[aria-label="Query 1 of group 1"]').should("have.value", "");
      cy.get('[role="tablist"][aria-label="Group 1 type"]')
        .contains("Independent")
        .should("have.attr", "aria-selected", "true");
    });

    it("refuses to save without a name and at least one query", () => {
      cy.contains("button", "Save Report").click();
      cy.toast("A report needs a name and at least one query.");
      cy.get("main").contains("h1", "Create Report").should("be.visible");
    });

    it("adds and removes queries inside a group", () => {
      cy.get('input[aria-label="Query 1 of group 1"]').type(
        "How many orders shipped late?",
        { delay: 0 },
      );
      cy.contains("button", "Add query").click();
      cy.get('input[aria-label="Query 2 of group 1"]')
        .should("exist")
        .type("What is the average basket size?", { delay: 0 });

      cy.get('button[aria-label="Remove query"]').last().click();
      cy.get('input[aria-label="Query 2 of group 1"]').should("not.exist");
      cy.get('input[aria-label="Query 1 of group 1"]').should(
        "have.value",
        "How many orders shipped late?",
      );
    });

    it("adds an independent and a sequential group, then removes one", () => {
      cy.contains("button", "Independent group").click();
      cy.contains("Group 2").should("be.visible");
      cy.contains("button", "Sequential group").click();
      cy.contains("Group 3").should("be.visible");
      cy.get('[role="tablist"][aria-label="Group 3 type"]')
        .contains("Sequential")
        .should("have.attr", "aria-selected", "true");

      cy.contains("b", "Group 3").parent().contains("button", "Remove").click();
      cy.contains("Group 3").should("not.exist");
    });

    it("switches a group between independent and sequential", () => {
      cy.get('[role="tablist"][aria-label="Group 1 type"]')
        .contains("Sequential")
        .click();
      cy.get('[role="tablist"][aria-label="Group 1 type"]')
        .contains("Sequential")
        .should("have.attr", "aria-selected", "true");
    });

    it("offers manual, daily and weekly schedules", () => {
      cy.get("#repSchedule").select("daily");
      cy.get("#repSchedule").should("have.value", "daily");
      cy.get("#repSchedule").select("weekly");
      cy.get("#repSchedule").should("have.value", "weekly");
      cy.get("#repSchedule").select("none");
    });

    it("returns to the list without creating anything", () => {
      cy.get("#repName").type("Cypress report", { delay: 0 });
      cy.contains("button", "Cancel").click();
      cy.get("main").contains("h1", "Reports").should("be.visible");
      cy.contains("Cypress report").should("not.exist");
    });
  });

  describe("run history", () => {
    /**
     * Both tests here need a settled list before deciding whether there is
     * anything to open: mid-load the page shows a skeleton, whose text matches
     * neither the empty state nor the unavailable notice, and the guard below
     * would fall through to a row that never arrives.
     */
    beforeEach(() => {
      cy.wait("@reports");
      cy.get("main").should(($main) => {
        const text = $main.text();
        expect(
          text.includes("No reports yet") ||
            UNAVAILABLE.test(text) ||
            /\d+ groups? ·/.test(text),
          "the list settled",
        ).to.be.true;
      });
    });

    it("opens an existing report and shows its runs, when there is one", () => {
      cy.get("main").then(($main) => {
        if (
          $main.text().includes("No reports yet") ||
          UNAVAILABLE.test($main.text())
        ) {
          cy.log("No reports available for this agent — nothing to open.");
          return;
        }

        cy.get("main").find("tbody tr").first().click();
        cy.contains("button", "Check status").should("be.visible");
        cy.contains("button", "Run now").should("be.visible");
        cy.contains(/query groups? ·/).should("be.visible");

        cy.get("main").should(($detail) => {
          const text = $detail.text();
          expect(
            text.includes("No runs yet") || text.includes("View results"),
            "the report rendered either its runs or its empty state",
          ).to.be.true;
        });

        cy.get("main").contains("button", "Reports").click();
        cy.get("main").contains("h1", "Reports").should("be.visible");
      });
    });

    /**
     * The regression this guards: the run body nests every answer under
     * `query_groups[].results[]`, and reading a flat `results` array off the
     * response left the page on its empty state while the API was returning a
     * full run. Walks list → report → run and asserts the questions render.
     */
    it("shows a finished run's questions and answers", () => {
      cy.get("main").then(($main) => {
        if (
          $main.text().includes("No reports yet") ||
          UNAVAILABLE.test($main.text())
        ) {
          cy.log("No reports available for this agent — nothing to open.");
          return;
        }

        cy.intercept("GET", API.reportRuns).as("runs");
        cy.get("main").find("tbody tr").first().click();
        cy.wait("@runs");

        cy.get("main").then(($detail) => {
          if (!$detail.text().includes("View results")) {
            cy.log("This report has no runs — nothing to open.");
            return;
          }

          cy.contains("button", "View results").first().click();
          cy.contains("button", "Run history").should("be.visible");

          // Either the run is still going, or its groups rendered with the
          // questions the report asked. Both are real states; an empty results
          // area on a finished run is not.
          cy.get("main", { timeout: 60000 }).should(($run) => {
            const text = $run.text();
            expect(
              text.includes("This run is still going") ||
                /Group 1 · (Independent|Sequential)/.test(text),
              "the run rendered its groups, or said it was still running",
            ).to.be.true;
          });
        });
      });
    });
  });
});
