import { API, ROUTES } from "../../support/routes";
import {
  STUB_AGENT_ID,
  STUB_AGENT_NAME,
  STUB_DB_NAME,
  stubBackend,
} from "../../support/stubs";

/**
 * The one suite that runs without a session — and the only one that stubs the
 * backend.
 *
 * `RequireSession` sends an unauthenticated browser to the SSO origin, so on a
 * machine (or a CI runner) with no session there is nothing to assert against:
 * the page is a redirect to a host that is not running. Stubbing `/user/me` and
 * the list endpoints gets past that and leaves something genuinely worth
 * checking — the app builds, mounts, routes, and paints its shell on every
 * product page.
 *
 * The data is fake and no assertion here depends on it beyond the shell. Real
 * behaviour is covered by the gated suites, against the real backend.
 */
describe("Database Agent · app boots", () => {
  beforeEach(stubBackend);

  it("forwards the retired /nl2sql/dashboard URL to the product", () => {
    // Two renames left URLs behind: the `/dashboard` segment went when the
    // marketing page above it did, and `/nl2sql` went when the product became
    // Database Agent. This URL carries both, and gets there in one hop. Old
    // bookmarks keep working through a client-side redirect, which is all a
    // static export can offer.
    cy.visit(ROUTES.legacyDashboard);
    cy.location("pathname", { timeout: 30000 }).should(
      "match",
      /\/database-agent\/?$/,
    );
    cy.get("main").contains("h1", "Your database agents").should("be.visible");
  });

  it("forwards the pre-rename /nl2sql home to /database-agent", () => {
    cy.visit(ROUTES.legacyHome);
    cy.location("pathname", { timeout: 30000 }).should(
      "match",
      /\/database-agent\/?$/,
    );
    cy.get("main").contains("h1", "Your database agents").should("be.visible");
  });

  it("keeps the query string when forwarding a pre-rename deep link", () => {
    // Every agent-scoped screen is reached with `?agentId=`, so a forward that
    // dropped the query would land people on the right screen with no agent.
    cy.visit(`${ROUTES.legacyConversations}?agentId=${STUB_AGENT_ID}`);
    cy.location("pathname", { timeout: 30000 }).should(
      "match",
      /\/database-agent\/conversations\/?$/,
    );
    cy.location("search").should("eq", `?agentId=${STUB_AGENT_ID}`);
  });

  it("paints Home with the workspace cards and the agent list", () => {
    cy.visitApp(ROUTES.home);
    cy.wait("@agents");

    cy.shellReady();
    cy.contains("Usage & Limits").should("be.visible");
    cy.contains("Add Credentials").should("be.visible");
    cy.contains(STUB_AGENT_NAME).should("be.visible");
    cy.contains(STUB_DB_NAME).should("be.visible");
    cy.contains("Showing 1 of 1").should("be.visible");
    // The shell's way out of the product. Since 75a14927 that is the marketing
    // site's own page for this product, not the agent host's root — the brand
    // beside it goes to this product's own Home, so leaving needs its own
    // control either way.
    cy.get('header a[aria-label="Back to the site"]').should(
      "have.attr",
      "href",
      "https://futuresmart.ai/solutions/database-agent",
    );
  });

  it("paints the rail and the agent chip on an agent-scoped page", () => {
    cy.visitApp(ROUTES.settings, STUB_AGENT_ID);
    cy.wait("@databases");

    cy.get('aside[aria-label="Main navigation"]').should("be.visible");
    // One link per entry in `RAIL_ITEMS` (nav.tsx): Home, Conversations,
    // Analytics, Share, Settings. Batch Query Reports is `hidden` and draws no
    // rail link.
    cy.get('aside[aria-label="Main navigation"] a').should("have.length", 5);
    cy.get("header").contains(STUB_AGENT_NAME).should("be.visible");
    cy.get("main").contains("h1", "Settings").should("be.visible");
  });

  it("renders every product page under the shell", () => {
    const pages: Array<[route: string, heading: string]> = [
      [ROUTES.settings, "Settings"],
      [ROUTES.share, "Share"],
      [ROUTES.reports, "Reports"],
    ];

    pages.forEach(([route, heading]) => {
      cy.visitApp(route, STUB_AGENT_ID);
      cy.get("main").contains("h1", heading).should("be.visible");
    });

    // Analytics is the agent dashboard's own page, mounted here over the NL2SQL
    // service's `/analytics/*` routes. It opens straight onto its window bar —
    // no in-`main` heading, because the topbar already titles the screen and a
    // second `h1` would give the page two. Tabs, not the tiles this used to
    // assert back when `/statistics` was the only readable source.
    cy.visitApp(ROUTES.analytics, STUB_AGENT_ID);
    cy.get("header").contains("h1", "Agent Analytics").should("be.visible");
    cy.get("main").contains("button", "Last 7 Days").should("be.visible");
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

    // Workspace-level, so they carry no agent.
    cy.visitApp(ROUTES.usage);
    // "Usage & Limits" names the screen in the topbar; the screen's own heading
    // is "Account Overview", as the design has it. `main` is scoped to the
    // first match because this view nests its own `main` for the content column
    // beside the section rail.
    cy.get("header").contains("h1", "Usage & Limits").should("be.visible");
    cy.get("main")
      .first()
      .contains("h1", "Account Overview")
      .should("be.visible");
    // The whole screen is four reads on the NL2SQL service. The Limits tab is
    // one of them, and it carries the token rate every cost figure is priced
    // at — no usage route returns a cost.
    cy.wait("@usageAggregate");
    cy.get("main")
      .first()
      .contains("Total estimated cost")
      .should("be.visible");
    cy.get("main").first().contains("Total Tokens").should("be.visible");
    cy.contains("button", "Limits").click();
    cy.wait("@ownerLimits");
    cy.get("main").first().contains("Your plan").should("be.visible");
    // Server-driven rows: the labels are the service's, not this app's. These
    // two sit below the fold on a panel this long, so they are scrolled to
    // rather than asserted where they happen to land.
    cy.get("main")
      .first()
      .contains("Chat requests per day")
      .scrollIntoView()
      .should("be.visible");
    // `limit: null` states the ceiling in words and draws no bar.
    cy.get("main")
      .first()
      .contains("no limit")
      .scrollIntoView()
      .should("be.visible");
    cy.get('aside[aria-label="Main navigation"]').should("not.exist");

    // Credentials is this product's own screen on the NL2SQL service's routes:
    // the design's board — three counts, then one row per stored provider — and
    // back goes to Home rather than to the agent dashboard.
    cy.visitApp(ROUTES.credentials);
    // The provider catalog is read for the "LLM providers" count; the board
    // itself is the stored credentials list.
    cy.wait("@ownerCredentials");
    cy.get("main").contains("h1", "Add Credentials").should("be.visible");
    cy.get("main").contains("Active keys").should("be.visible");
    cy.get("main").contains("Configured Providers").should("be.visible");
    // Wire ids are not names: the row carries the provider's label.
    cy.get("main").contains("OpenAI").should("be.visible");
    // Keys are write-only, and the mask itself starts covered — the eye
    // uncovers the service's own mask, which is all there is to uncover.
    cy.get("main").contains("sk-...48sA").should("not.exist");
    cy.get("main").find('button[aria-label="Show the OpenAI key"]').click();
    cy.get("main").contains("sk-...48sA").should("be.visible");
    // Row actions are icon-only, so the label lives on the button.
    cy.get("main")
      .find('button[aria-label="Edit the OpenAI credential"]')
      .should("exist");
    cy.get("main")
      .find('button[aria-label="Delete the OpenAI credential"]')
      .should("exist");
    cy.get("main")
      .contains("a", "Back to Dashboard")
      .should("have.attr", "href")
      .and("match", /\/database-agent\/?$/);
    cy.get('aside[aria-label="Main navigation"]').should("not.exist");
  });

  it("sends the Home credentials card to the Credentials screen", () => {
    cy.visitApp(ROUTES.home);
    cy.wait("@agents");

    // The card is a link, not a dialog: the keys live on their own screen, and
    // the add form is a dialog on that screen.
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
    });
  });

  /**
   * "Shared With Me", while the service has no shared-agents route.
   *
   * `fetchSharedAgents` returns nothing and makes no request — the standalone
   * product dropped `/api/chat/v1/agents/shared` with the rest of the chat
   * service, and the NL2SQL service has no equivalent. So the tab has an empty
   * state rather than cards, and there is no call to wait on. The tests that
   * covered grouping by owner, opening a shared card and its row actions are
   * deliberately not here: they described a capability this product cannot have
   * until that endpoint exists, and a spec that fails for that reason reports
   * nothing useful. They come back with the endpoint.
   */
  describe("Shared With Me", () => {
    it("says nothing is shared, and asks for no shared-agents call", () => {
      cy.intercept("GET", /\/agents\/shared/, cy.spy().as("sharedCall"));

      cy.visitApp(ROUTES.home);
      cy.wait("@agents");
      cy.tab("Shared With Me");

      cy.get("main").contains("No shared agents").should("be.visible");
      cy.get("@sharedCall").should("not.have.been.called");
    });
  });

  /**
   * With no `?agentId=`, Analytics reads the fleet grid first. This workspace's
   * agents have recorded nothing, so the grid has no rows to show and falls
   * back to the picker — the state a brand-new workspace is always in, since
   * analytics records nothing retroactively.
   */
  it("asks which agent to open when the URL names none", () => {
    cy.visitApp(ROUTES.analytics);
    cy.wait("@agents");
    cy.wait("@analyticsOverview");
    cy.get("main").contains("h1", "Select an agent").should("be.visible");
    cy.contains("1 database connected").should("be.visible");
  });

  /**
   * The same URL, once an agent has recorded something: the fleet grid, from
   * `GET /v1/agents/analytics/overview`. The route existed and nothing called
   * it, so this landing state used to be a picker that said nothing about
   * which agent was worth opening.
   */
  it("lists every agent's numbers when the fleet has traffic", () => {
    cy.intercept("GET", API.analyticsOverview, {
      statusCode: 200,
      body: {
        total_agents: 1,
        summary: { total_queries: 73, total_cost: 0.1858, cost_complete: true },
        agents: [
          {
            // The NL2SQL service keys analytics by the same id it lists agents
            // under, which is what makes the row linkable.
            agent_id: STUB_AGENT_ID,
            owner_id: "cypress@futuresmart.ai",
            name: null,
            total_queries: 73,
            unique_users: 5,
            answered: 61,
            unanswered: 12,
            success_rate: 83.6,
            failed_api_requests: 0,
            avg_ms: 6495,
            p95_ms: 10045,
            total_tokens: 529338,
            total_cost: 0.185843,
            avg_cost_per_query: 0.002546,
            cost_complete: true,
            top_failure_category: "sql_error",
          },
        ],
      },
    }).as("fleet");

    cy.visitApp(ROUTES.analytics);
    cy.wait("@fleet");

    cy.get("main").contains("All agents").should("be.visible");
    cy.get("main").contains("83.6%").should("be.visible");
    cy.get("main").contains("sql_error").should("be.visible");

    // Rows are keyed by the NL2SQL service id; the link has to carry the agent
    // record whose `service_ref` that is, or the page it opens cannot resolve
    // the agent.
    cy.get("main")
      .contains("a", STUB_AGENT_ID)
      .should("have.attr", "href")
      .and("contain", `agentId=${STUB_AGENT_ID}`);
  });

  it("opens the New agent wizard and walks its first step", () => {
    cy.visitApp(ROUTES.home);
    cy.wait("@agents");

    cy.contains("button", "New agent").first().click();
    cy.dialog().within(() => {
      cy.contains("New database agent").should("be.visible");
      cy.get("#wzName").type("Smoke agent", { delay: 0 });
      cy.contains("button", "Next — connect a database").click();
      cy.get("#wzEngine").should("have.value", "postgresql");
      cy.get("#wzPort").should("have.value", "5432");
      cy.contains("button", "Cancel").should("not.exist");
      cy.contains("button", "Back").click();
      cy.get("#wzName").should("have.value", "Smoke agent");
    });
  });
});
