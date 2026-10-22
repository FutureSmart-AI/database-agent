import { isAuthenticated } from "../../support/gate";
import { API, ROUTES } from "../../support/routes";

/**
 * One agent, cradle to grave.
 *
 * Unlike the rest of the suite — which is deliberately read-only against a
 * workspace someone else owns — this spec creates its **own** throwaway agent,
 * drives every flow the product has against it, and deletes it again. Nothing
 * it writes touches an agent it did not create.
 *
 * The order matters and the steps share state, so they are sequential `it`
 * blocks over a module-scoped context rather than independent tests. A step
 * that cannot run because an earlier one failed is skipped with its reason, and
 * the `after` hook deletes the agent through the API whatever happened — a
 * failed run must not leak an agent into the workspace.
 *
 *   bun dev
 *   CYPRESS_E2E_AUTHENTICATED=1 \
 *   CYPRESS_DB_HOST=… CYPRESS_DB_NAME=… CYPRESS_DB_USER=… CYPRESS_DB_PASSWORD=… \
 *   bun run test:cy -- --spec cypress/e2e/nl2sql/00-full-journey.cy.ts
 */

interface DbConfig {
  engine: string;
  host: string;
  port: string;
  name: string;
  user: string;
  password: string;
  description: string;
}

const db: DbConfig = {
  engine: (Cypress.env("DB_ENGINE") as string) || "postgresql",
  host: (Cypress.env("DB_HOST") as string) || "",
  port: (Cypress.env("DB_PORT") as string) || "",
  name: (Cypress.env("DB_NAME") as string) || "",
  user: (Cypress.env("DB_USER") as string) || "",
  password: (Cypress.env("DB_PASSWORD") as string) || "",
  description:
    (Cypress.env("DB_DESCRIPTION") as string) ||
    "End-to-end test database. Holds the application's operational tables — " +
      "use it for any question about this workspace's own data.",
};

const ASK_QUERY =
  (Cypress.env("ASK_QUERY") as string) ||
  "Count the rows in each of the five largest tables and show them as a chart.";

const hasCredentials = Boolean(db.host && db.name && db.user && db.password);

/**
 * Shared across the steps. `agentId` is filled by the create step; every later
 * step needs it, and says so rather than failing on a selector.
 */
const journey = {
  agentName: "",
  agentId: "",
  /** The step running right now, so `afterEach` can name the one that broke. */
  currentStep: "",
  /** Set once a step fails, so the ones after it report why they stopped. */
  brokenAt: "",
};

/**
 * Wraps a step so the ones after a failure are reported as skipped-with-reason
 * rather than each failing on its own selector — one broken run should read as
 * "creating the agent failed", not as eleven unrelated failures.
 */
function step(name: string, body: (this: Mocha.Context) => void) {
  return function (this: Mocha.Context) {
    if (name !== "create") {
      if (journey.brokenAt) {
        cy.log(`Skipped — the journey stopped at "${journey.brokenAt}".`);
        this.skip();
        return;
      }
      if (!journey.agentId) {
        cy.log("Skipped — no agent was created.");
        this.skip();
        return;
      }
    }
    journey.currentStep = name;
    body.call(this);
  };
}

const suite = isAuthenticated() && hasCredentials ? describe : describe.skip;

suite("Database Agent · full lifecycle journey", () => {
  before(() => {
    // A name nobody else in the workspace can collide with, and one a human
    // can recognise as test debris if a run is ever killed mid-flight.
    journey.agentName = `E2E Journey ${new Date()
      .toISOString()
      .replace(/[:.]/g, "-")}`;
  });

  afterEach(function () {
    if (this.currentTest?.state === "failed" && !journey.brokenAt) {
      journey.brokenAt = journey.currentStep;
    }
  });

  after(() => {
    // Safety net. The delete step below is the assertion; this is what stops a
    // failed run from leaving an agent behind.
    if (!journey.agentId) return;
    const base = (Cypress.env("API_BASE") as string).replace(/\/+$/, "");
    cy.request({
      method: "DELETE",
      url: `${base}/nl2sql/api/v1/agents/${journey.agentId}`,
      failOnStatusCode: false,
    }).then((response) => {
      cy.log(`Cleanup delete → ${response.status}`);
    });
  });

  // ── 1. create ─────────────────────────────────────────────────────────────

  it(
    "creates an agent, testing the connection before anything is stored",
    step("create", function () {
      cy.intercept("POST", API.databaseTest).as("testConnection");
      cy.intercept("POST", /\/nl2sql\/api\/v1\/agents(\?|$)/).as("provision");
      cy.intercept("POST", API.databases).as("addDatabase");

      cy.visitApp(ROUTES.home);
      cy.get("main")
        .contains("h1", "Your database agents")
        .should("be.visible");
      cy.contains("button", "New agent").first().click();

      cy.dialog().within(() => {
        cy.get("#wzName").type(journey.agentName, { delay: 0 });
        cy.contains("button", "Next — connect a database").click();

        cy.get("#wzEngine").select(db.engine);
        if (db.port) cy.get("#wzPort").clear().type(db.port, { delay: 0 });
        cy.get("#wzHost").type(db.host, { delay: 0 });
        cy.get("#wzDb").type(db.name, { delay: 0 });
        cy.get("#wzUser").type(db.user, { delay: 0 });
        cy.get("#wzPass").type(db.password, { delay: 0, log: false });
        cy.get("#wzDesc").type(db.description, { delay: 0 });

        cy.contains("button", "Test & create agent").click();
      });

      // The three provisioning steps are real calls, in this order.
      cy.wait("@testConnection", { timeout: 120000 })
        .its("response.body.status")
        .should("eq", "connected");
      cy.wait("@provision", { timeout: 120000 })
        .its("response.statusCode")
        .should("be.oneOf", [200, 201]);
      cy.wait("@addDatabase", { timeout: 180000 })
        .its("response.statusCode")
        .should("be.oneOf", [200, 201]);

      cy.dialog()
        .contains(`${journey.agentName} is ready`, { timeout: 180000 })
        .should("be.visible")
        .and("match", /\d+ tables? found across 1 database/);

      // The wizard hands off to the new agent's conversation — which is where
      // its id becomes visible to the test.
      cy.dialog().contains("button", "Ask a question →").click();
      cy.location("search", { timeout: 60000 })
        .should("match", /agentId=.+/)
        .then((search) => {
          journey.agentId = new URLSearchParams(search).get("agentId") ?? "";
          expect(journey.agentId, "the new agent's id").to.not.be.empty;
        });
    }),
  );

  it(
    "lists the new agent on Home with its database",
    step("home", function () {
      cy.intercept("GET", API.agents).as("agents");
      cy.visitApp(ROUTES.home);
      cy.wait("@agents");

      cy.get('input[aria-label="Search agents"]').type(journey.agentName, {
        delay: 0,
      });
      cy.contains(journey.agentName).should("be.visible");
      cy.contains("1 database connected").should("be.visible");
      cy.get(`[aria-label="Settings for ${journey.agentName}"]`).should(
        "exist",
      );
    }),
  );

  // ── 2. settings ───────────────────────────────────────────────────────────

  it(
    "reports the database as reachable from Settings",
    step("check-databases", function () {
      cy.intercept("GET", API.databases).as("databases");
      cy.intercept("POST", API.databasesCheck).as("checkAll");

      cy.visitApp(ROUTES.settings, journey.agentId);
      cy.wait("@databases");

      cy.get("main").contains(db.name).should("be.visible");
      cy.get("main")
        .contains(/^[1-9]\d* tables?$/)
        .should("be.visible");

      cy.contains("button", "Check all").click();
      cy.wait("@checkAll").its("response.statusCode").should("eq", 200);
      cy.toast(/1 database answered/);
    }),
  );

  it(
    "saves the database description and the table set it may read",
    step("configure-database", function () {
      cy.intercept("GET", API.databases).as("databases");
      cy.intercept("GET", API.tables).as("tables");

      cy.visitApp(ROUTES.settings, journey.agentId);
      cy.wait("@databases");
      cy.contains("button", "Configure").click();
      cy.contains("Configure —").should("be.visible");

      // The description the wizard stored is the one the router will read.
      cy.get('textarea[id^="desc-"]').should("have.value", db.description);
      cy.get('textarea[id^="desc-"]').type(" Updated by the journey run.", {
        delay: 0,
      });
      cy.contains("button", "Save description").click();
      cy.toast(/Description saved for/);

      cy.get('[role="tablist"][aria-label="Database configuration"]')
        .contains("Tables & visibility")
        .click();
      cy.wait("@tables");

      // Every table is readable when an agent is built; switching one off and
      // back on is the visibility write, round-tripped through the service.
      cy.get("main")
        .find("button")
        .filter(':contains("Included")')
        .first()
        .then(($toggle) => {
          cy.wrap($toggle).click();
          cy.wrap($toggle).should("contain.text", "Excluded");
          cy.wrap($toggle).click();
          cy.wrap($toggle).should("contain.text", "Included");
        });

      // A description on one table, saved for real.
      cy.get('input[aria-label^="Description for "]')
        .first()
        .clear()
        .type("Described by the end-to-end journey.", { delay: 0 });
      cy.contains("button", /^(Save|Update)$/).click();
      cy.toast(/table description|Saved descriptions|Updated/i);
    }),
  );

  it(
    "teaches the agent a few-shot example",
    step("few-shot", function () {
      cy.intercept("GET", API.databases).as("databases");
      cy.intercept("GET", API.fewShot).as("fewShot");
      cy.intercept("POST", API.fewShot).as("saveFewShot");

      cy.visitApp(ROUTES.settings, journey.agentId);
      cy.wait("@databases");
      cy.contains("button", "Configure").click();
      cy.get('[role="tablist"][aria-label="Database configuration"]')
        .contains("Few-shot examples")
        .click();
      cy.wait("@fewShot");

      cy.contains("button", "Paste JSON").click();
      cy.dialog().within(() => {
        cy.get('textarea[aria-label="JSON to import"]').type(
          JSON.stringify([
            {
              natural_query: "how many rows are in the largest table?",
              sql_query: "SELECT COUNT(*) FROM information_schema.tables",
            },
          ]),
          { parseSpecialCharSequences: false, delay: 0 },
        );
        cy.contains("button", "Apply").click();
      });
      cy.toast(/Added 1 example/);

      cy.contains("button", /^(Save|Update)$/).click();
      cy.wait("@saveFewShot").its("response.statusCode").should("eq", 200);
      cy.toast(/example|indexed/i);
    }),
  );

  it(
    "turns on charts, sources and a suggested question, and they persist",
    step("answers", function () {
      cy.intercept("GET", API.databases).as("databases");
      cy.intercept(
        "PATCH",
        /\/nl2sql\/api\/v1\/agents\/[^/?#]+\/config\/params/,
      ).as("saveParams");

      cy.visitApp(ROUTES.settings, journey.agentId);
      cy.wait("@databases");
      cy.tab("Answers");

      cy.get("#agName").should("have.value", journey.agentName);

      // Charts are what the chat step asserts on, so this is the switch that
      // makes the rest of the journey meaningful.
      ["Show sources", "Follow-up questions", "Charts"].forEach((feature) => {
        cy.contains("label", feature)
          .find('input[type="checkbox"]')
          .check({ force: true });
      });

      cy.contains("button", "Add Question").click();
      cy.get('input[aria-label^="Suggested question "]')
        .last()
        .type("Which tables hold the most rows?", { delay: 0 });

      cy.contains("button", "Save Changes").click();
      cy.wait("@saveParams")
        .its("response.statusCode")
        .should("be.oneOf", [200, 204]);
      cy.toast("Answer settings saved.");

      // Reloaded from the API, not from the form's own state.
      cy.visitApp(ROUTES.settings, journey.agentId);
      cy.wait("@databases");
      cy.tab("Answers");
      cy.contains("label", "Charts")
        .find('input[type="checkbox"]')
        .should("be.checked");
      cy.get('input[aria-label^="Suggested question "]')
        .last()
        .should("have.value", "Which tables hold the most rows?");
    }),
  );

  it(
    "saves a node configuration change under Advanced",
    step("advanced", function () {
      cy.intercept("GET", API.databases).as("databases");
      cy.intercept("GET", API.nodes).as("nodes");

      cy.visitApp(ROUTES.settings, journey.agentId);
      cy.wait("@databases");
      cy.tab("Advanced");
      cy.wait("@nodes");

      cy.get("main").find("details").first().find("summary").click();
      cy.get('input[aria-label^="Temperature for "]')
        .first()
        .clear()
        .type("0.2", { delay: 0 });
      cy.get("main")
        .find("details")
        .first()
        .find("summary")
        .should("contain.text", "changed");

      cy.contains("button", "Save node configuration").click();
      cy.toast(/saved|configuration/i);
    }),
  );

  it(
    "opens both share channels and saves the appearance",
    step("share", function () {
      cy.intercept("GET", API.databases).as("databases");
      cy.intercept(
        "PATCH",
        /\/api\/chat\/v1\/agents\/[^/?#]+\/config\/params/,
      ).as("saveParams");

      cy.visitApp(ROUTES.share, journey.agentId);
      cy.wait("@databases");

      // The snippet people paste carries this agent, not a placeholder.
      cy.get("main")
        .contains(`data-agent-id="${journey.agentId}"`)
        .should("be.visible");
      cy.get("main")
        .contains(`/agent/${journey.agentId}/?mode=fullscreen`)
        .should("be.visible");

      cy.get('[role="switch"][aria-label="Enable the chat bubble"]').then(
        ($toggle) => {
          if ($toggle.attr("aria-checked") !== "true") cy.wrap($toggle).click();
        },
      );
      cy.get('[role="switch"][aria-label="Enable the full-page link"]').then(
        ($toggle) => {
          if ($toggle.attr("aria-checked") !== "true") cy.wrap($toggle).click();
        },
      );

      cy.get('input[aria-label="Domain to allow"]')
        .first()
        .type("journey.example.com", { delay: 0 });
      cy.contains("button", "Add").first().click();
      cy.contains("journey.example.com").should("be.visible");

      cy.get("#apGreet")
        .clear()
        .type("Ask me anything about this database.", { delay: 0 });

      cy.contains("button", "Save appearance").click();
      cy.wait("@saveParams")
        .its("response.statusCode")
        .should("be.oneOf", [200, 204]);
      cy.toast(/Saved — heading, greeting/);

      // Round-trip: the toggles and the domain came back from the API.
      cy.visitApp(ROUTES.share, journey.agentId);
      cy.wait("@databases");
      cy.get('[role="switch"][aria-label="Enable the chat bubble"]').should(
        "have.attr",
        "aria-checked",
        "true",
      );
      cy.contains("journey.example.com").should("be.visible");
    }),
  );

  // ── 3. ask, and see the chart ─────────────────────────────────────────────

  it(
    "answers a question with SQL, result rows and a rendered chart",
    step("chat", function () {
      cy.intercept("POST", API.chat).as("ask");

      cy.visitApp(ROUTES.conversations, journey.agentId);
      cy.contains("h1", "Conversations", { timeout: 60000 }).should(
        "be.visible",
      );
      cy.contains("button", "New chat").click();

      cy.get('textarea[aria-label="Message"]').type(ASK_QUERY, { delay: 0 });
      cy.get('[aria-label="Send message"]').click();

      cy.contains(ASK_QUERY).should("be.visible");
      cy.wait("@ask", { timeout: 300000 })
        .its("response.statusCode")
        .should("eq", 200);

      // The answer is here once the sources panel is — that button only exists
      // on a turn the agent actually produced NL2SQL output for.
      cy.contains("button", "Data Sources & Execution Details", {
        timeout: 300000,
      })
        .should("be.visible")
        .click();

      cy.contains("Executed SQL").should("be.visible");
      cy.contains("SELECT", { matchCase: false }).should("be.visible");

      cy.contains("Result Data").click();
      cy.contains(/rows|Preview \(first/).should("be.visible");

      // The chart itself — the reason `chart_output` was switched on above.
      // The tab shows the agent's chart *metadata*; the drawn chart lives one
      // click further, in the chart viewer.
      cy.contains("Chart Metadata").click();
      cy.contains("Suggested chart:").should("be.visible");
      cy.contains("button", "Open in chart viewer").click();

      cy.dialog().within(() => {
        cy.contains("Chart Viewer").should("be.visible");
        cy.get("svg.recharts-surface", { timeout: 60000 })
          .should("have.length.greaterThan", 0)
          .and("be.visible");
        // A drawn chart has marks, not just an empty plotting surface.
        cy.get(
          ".recharts-bar-rectangle, .recharts-line-curve, .recharts-pie-sector, .recharts-symbols",
        ).should("have.length.greaterThan", 0);
      });
      cy.get('[aria-label="Close"]').last().click();
    }),
  );

  it(
    "shows the question in Analytics, with the overview charts drawn",
    step("analytics", function () {
      cy.intercept("GET", API.scorecard).as("scorecard");
      cy.intercept("GET", API.queries).as("queries");

      cy.visitApp(ROUTES.analytics, journey.agentId);
      cy.get("main")
        .contains("h1", `Agent Analytics — ${journey.agentName}`, {
          timeout: 60000,
        })
        .should("be.visible");
      cy.wait("@scorecard");

      cy.contains("Total Queries").should("be.visible");
      cy.get("main svg.recharts-surface", { timeout: 60000 }).should(
        "have.length.greaterThan",
        0,
      );

      cy.tab("Query Logs");
      cy.wait("@queries");
      // The dashboard service records a query asynchronously, so this is the
      // one assertion in the journey that is allowed to arrive late.
      cy.contains("tbody", ASK_QUERY.slice(0, 30), { timeout: 120000 }).should(
        "be.visible",
      );

      cy.get('button[aria-label^="Expand "]').first().click();
      cy.contains("Chat ID").should("be.visible");
      cy.contains("Session ID").should("be.visible");
    }),
  );

  it(
    "counts the agent's tokens on the workspace Usage page",
    step("usage", function () {
      cy.intercept("GET", API.usageAggregate).as("usageAggregate");
      cy.visitApp(ROUTES.usage);
      cy.wait("@usageAggregate");

      cy.get('nav[aria-label="Usage sections"]')
        .contains("button", "Agents")
        .click();
      cy.get("main").contains("th", "Agent ID").should("be.visible");
      // Usage aggregation lags the query itself; the assertion is that the page
      // reports per-agent rows, not that this agent has already landed in them.
      cy.get("main").find("tbody").should("exist");
    }),
  );

  // ── 4. batch reports ──────────────────────────────────────────────────────

  it(
    "creates and deletes a batch report on this agent",
    step("reports", function () {
      cy.intercept("GET", API.reports).as("reports");
      cy.intercept("POST", API.reports).as("createReport");

      cy.visitApp(ROUTES.reports, journey.agentId);
      cy.get("main")
        .contains("h1", "Reports", { timeout: 60000 })
        .should("be.visible");

      cy.contains("button", "New Report").click();
      cy.get("#repName").type("Journey report", { delay: 0 });
      cy.get('input[aria-label="Query 1 of group 1"]').type(
        "How many tables does this database have?",
        { delay: 0 },
      );
      // Saved, not run: a run costs a real query per line.
      cy.contains("button", "Save Report").click();
      cy.wait("@createReport")
        .its("response.statusCode")
        .should("be.oneOf", [200, 201]);
      cy.toast("Report created.");

      cy.contains("Journey report").should("be.visible");
      cy.get('button[aria-label="Delete Journey report"]').click();
      cy.toast("Journey report deleted.");
      cy.contains("Journey report").should("not.exist");
    }),
  );

  // ── 5. delete ─────────────────────────────────────────────────────────────

  it(
    "deletes the agent, and it leaves the workspace",
    step("delete", function () {
      cy.intercept("GET", API.agents).as("agents");
      cy.intercept("DELETE", /\/api\/chat\/v1\/agents\/[^/?#]+$/).as(
        "deleteAgent",
      );

      cy.visitApp(ROUTES.home);
      cy.wait("@agents");
      cy.get('input[aria-label="Search agents"]').type(journey.agentName, {
        delay: 0,
      });

      cy.get(`[aria-label="Delete ${journey.agentName}"]`).click();
      cy.dialog().within(() => {
        cy.contains(`Delete ${journey.agentName}?`).should("be.visible");
        cy.contains("The databases themselves are untouched.").should(
          "be.visible",
        );
        cy.contains("button", "Delete agent").click();
      });

      cy.wait("@deleteAgent")
        .its("response.statusCode")
        .should("be.oneOf", [200, 202, 204]);
      cy.toast(`${journey.agentName} deleted.`);
      cy.contains(journey.agentName).should("not.exist");

      // The `after` hook has nothing left to clean up.
      journey.agentId = "";
    }),
  );
});
