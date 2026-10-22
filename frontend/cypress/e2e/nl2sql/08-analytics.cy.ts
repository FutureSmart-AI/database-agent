import { describeAuthed } from "../../support/gate";
import { API, ROUTES } from "../../support/routes";

/**
 * Analytics — the agent dashboard's analytics page, on NL2SQL's own endpoints.
 *
 * The toolbar, tab bar, KPI cards, charts and tables are imported from
 * `src/app/dashboard/analytics`, not copied, so most of what this spec guards is
 * that the shared page is actually mounted and pointed at the right service:
 * the same window presets, the same tabs in the same order, and every read going
 * to `/nl2sql/api/v1/agents/{id}/analytics/…` rather than the dashboard routes,
 * which answer 403 for an `NL2SQL_…` id.
 *
 * Assertions are deliberately shape-level, not value-level. A QA agent's numbers
 * move between runs, and analytics has no historical backfill — a fresh agent
 * answers 404 on four of the six routes, which the page renders as zeros rather
 * than as an error. Both states have to pass.
 */
describeAuthed("Database Agent · Analytics", () => {
  beforeEach(() => {
    cy.intercept("GET", API.scorecard).as("scorecard");
    cy.intercept("GET", API.trends).as("trends");
    cy.intercept("GET", API.queries).as("queries");
    cy.intercept("GET", API.failures).as("failures");
    cy.intercept("GET", API.dashboardScorecard).as("dashboardScorecard");
    cy.intercept("GET", API.dashboardTrends).as("dashboardTrends");
    cy.intercept("GET", API.dashboardQueries).as("dashboardQueries");

    cy.visitAgent(ROUTES.analytics);
    // The shell renders before the scorecard lands; the tab bar is the anchor
    // now that the page has no in-main heading (the topbar carries the title).
    cy.get("main")
      .contains('[role="tab"]', "Overview", { timeout: 60000 })
      .should("be.visible");
  });

  it("reads the scorecard from the NL2SQL service", () => {
    cy.wait("@scorecard")
      .its("response.statusCode")
      // 404 is the documented "no data yet" state, not a failure.
      .should("be.oneOf", [200, 404]);
  });

  it("never asks the dashboard service for an NL2SQL agent", () => {
    cy.wait("@scorecard");
    cy.get("@dashboardScorecard.all").should("have.length", 0);
    cy.get("@dashboardTrends.all").should("have.length", 0);
    cy.get("@dashboardQueries.all").should("have.length", 0);
  });

  it("offers the agent dashboard's five tabs, plus Failures", () => {
    cy.get('main [role="tab"]').should(($tabs) => {
      expect([...$tabs].map((tab) => tab.textContent?.trim())).to.deep.equal([
        "Overview",
        "Quality & Accuracy",
        "Performance",
        "Cost",
        "Failures",
        "Query Logs",
      ]);
    });
  });

  it("keeps the Overview card slots the agent dashboard has", () => {
    cy.wait("@scorecard");
    [
      "Total Queries",
      "Success Rate",
      "Avg Response Time",
      "Total Cost",
    ].forEach((label) => {
      cy.get("main").contains(label).should("be.visible");
    });
  });

  it("offers the same date window presets as the agent dashboard", () => {
    cy.get("main").contains("button", "Last 7 Days").should("be.visible");
    cy.get("main").contains("button", "Last 30 Days").should("be.visible");
    cy.get("main").contains("Custom Range").should("be.visible");
  });

  it("re-reads the window when the period changes", () => {
    cy.wait("@scorecard");
    cy.get("main").contains("button", "Last 30 Days").click();
    cy.location("search").should("contain", "period=month");
    cy.wait("@scorecard").its("request.url").should("contain", "period=month");
  });

  it("moves between tabs and keeps the choice in the URL", () => {
    cy.tab("Performance");
    cy.location("search").should("contain", "tab=performance");
    cy.get("main").contains("P95 Latency").should("be.visible");

    cy.tab("Cost");
    cy.location("search").should("contain", "tab=cost");
    cy.get("main").contains("Total Tokens").should("be.visible");
  });

  it("serves four tabs from the one scorecard, with no new request", () => {
    cy.wait("@scorecard");
    cy.get("@scorecard.all").then((before) => {
      cy.tab("Quality & Accuracy");
      cy.get("main").contains("Answered").should("be.visible");
      cy.tab("Cost");
      cy.get("main").contains("Total Cost").should("be.visible");
      // Trends and the query log are their own reads; the scorecard is not
      // re-fetched just to re-render the same payload differently.
      cy.get("@scorecard.all").should(
        "have.length",
        (before as unknown[]).length,
      );
    });
  });

  it("reads failures from the NL2SQL-only route", () => {
    cy.tab("Failures");
    cy.location("search").should("contain", "tab=failures");
    cy.wait("@failures")
      .its("response.statusCode")
      .should("be.oneOf", [200, 404]);
    cy.get("main").contains("Total Failures").should("be.visible");
    cy.get("main").contains("Failures by Category").should("be.visible");
  });

  it("opens the tab named in the URL on a cold load", () => {
    // Built by hand rather than with `visitAgent`, which appends `?agentId=`
    // and would leave two query strings on the URL.
    cy.nl2sqlAgentId().then((agentId) => {
      cy.visit(`${ROUTES.analytics}?agentId=${agentId}&tab=failures`);
      cy.get('main [role="tab"]', { timeout: 60000 })
        .contains("Failures")
        .should("have.attr", "aria-selected", "true");
    });
  });

  /**
   * `chat_id` is the join key from a conversation to its analytics row, and the
   * API treats it as an exact lookup that ignores the window — so the page has
   * to say the window no longer applies and offer the way back.
   */
  it("opens one query from a ?chat_id= deep link", () => {
    cy.nl2sqlAgentId().then((agentId) => {
      cy.visit(
        `${ROUTES.analytics}?agentId=${agentId}&tab=querylogs&chat_id=probe-chat-id`,
      );
      cy.wait("@queries", { timeout: 60000 })
        .its("request.url")
        .should("contain", "chat_id=probe-chat-id");
      cy.get("main").contains("Showing one query").should("be.visible");
      // Every other filter is suppressed while one query is pinned.
      cy.get("main").find('[aria-label="Status"]').should("not.exist");

      cy.get("main").contains("Show the full log").click();
      cy.location("search").should("not.contain", "chat_id");
      cy.get("main").find('[aria-label="Status"]').should("be.visible");
    });
  });

  it("loads the query log on its own tab", () => {
    cy.tab("Query Logs");
    cy.location("search").should("contain", "tab=querylogs");
    cy.wait("@queries")
      .its("response.statusCode")
      .should("be.oneOf", [200, 404]);
  });

  /**
   * The Route filter sends `/queries?route=`, whose values are this service's
   * query plans. It used to be the agent dashboard's list of service families,
   * which NL2SQL does not recognise — so every option returned an empty log
   * and nothing said why. The options now come from the service's OpenAPI
   * document via `src/generated/analyticsContract.ts`.
   */
  it("filters the log by a route this service actually accepts", () => {
    cy.tab("Query Logs");
    cy.get('main [aria-label="Route"]').as("route");
    cy.get("@route")
      .find("option")
      .should(($options) => {
        const values = [...$options].map((o) => (o as HTMLOptionElement).value);
        expect(values).to.include("sql");
        expect(values).to.not.include("knowledge");
      });

    cy.get("@route").select("sql");
    cy.wait("@queries").its("request.url").should("contain", "route=sql");
  });
});

/**
 * The fleet grid — `GET /v1/agents/analytics/overview`, the one analytics route
 * that is not per-agent. Analytics used to open on a bare agent picker and
 * never call it, so "which agent is failing, which is expensive" had no screen.
 */
describeAuthed("Database Agent · Analytics fleet grid", () => {
  it("reads every agent's analytics when the URL names none", () => {
    cy.intercept("GET", API.analyticsOverview).as("overview");
    cy.visit(ROUTES.analytics);

    cy.wait("@overview", { timeout: 60000 })
      .its("response.statusCode")
      // 404 is the documented "nothing recorded yet" state.
      .should("be.oneOf", [200, 404]);

    // Either the grid or — for a workspace with no traffic — the picker it
    // falls back to. Both are a way in to one agent; neither is an error.
    cy.get("main")
      .contains(/All agents|Select an agent/, { timeout: 60000 })
      .should("be.visible");
  });

  it("never sends owner_id — a session caller is scoped server-side", () => {
    cy.intercept("GET", API.analyticsOverview).as("overview");
    cy.visit(ROUTES.analytics);
    cy.wait("@overview", { timeout: 60000 })
      .its("request.url")
      .should("not.contain", "owner_id");
  });
});
