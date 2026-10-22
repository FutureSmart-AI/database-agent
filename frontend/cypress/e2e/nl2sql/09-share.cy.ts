import { describeAuthed } from "../../support/gate";
import { API, ROUTES } from "../../support/routes";

/**
 * Share — the three ways out of the product (bubble, full page, API), the
 * appearance draft and its live preview, and the people/keys lists.
 *
 * Every feature on this screen is a disclosure row that starts CLOSED, and a
 * closed row does not render its body at all, so a test asserting on anything
 * inside one opens it first with `openRow`. What each row states while closed —
 * its name, its purpose, its primary control — is asserted without opening.
 *
 * The two irreversible actions on this page — issuing an API key and inviting
 * someone — are asserted as affordances only. A run must not leave a live key
 * or an invitation behind.
 */

/** Opens one row by the id its header controls, and leaves an open row open. */
const openRow = (row: string) =>
  cy.get(`button[aria-controls="share-${row}"]`).then(($header) => {
    if ($header.attr("aria-expanded") === "false") cy.wrap($header).click();
  });

describeAuthed("Database Agent · Share", () => {
  beforeEach(() => {
    cy.intercept("GET", API.databases).as("databases");
    cy.intercept("GET", API.apiKeys).as("apiKeys");

    cy.visitAgent(ROUTES.share);
    cy.get("main")
      .contains("h1", "Share", { timeout: 60000 })
      .should("be.visible");
  });

  it("keeps what other people asked on its own tab, read-only", () => {
    cy.get('[role="tablist"][aria-label="Share sections"]').within(() => {
      cy.contains("Set up").should("have.attr", "aria-selected", "true");
      cy.contains("Activity").click();
    });
    // Set up is replaced, not merely scrolled past.
    cy.get('button[aria-controls="share-widget"]').should("not.exist");
    cy.get('[role="tablist"][aria-label="Activity source"]').within(() => {
      cy.contains("Shared users").should("have.attr", "aria-selected", "true");
      cy.contains("Widget").click();
      cy.contains("Widget").should("have.attr", "aria-selected", "true");
    });
    cy.get("main").then(($main) => {
      const text = $main.text();
      expect(
        /Nothing from the bubble yet/.test(text) ||
          /\d+ of \d+ shown/.test(text),
        "the activity list rendered either its rows or its empty state",
      ).to.be.true;
    });
    cy.get('[role="tablist"][aria-label="Share sections"]')
      .contains("Set up")
      .click();
    cy.get('button[aria-controls="share-widget"]').should("exist");
  });

  it("starts with every feature collapsed, and opens them all at once", () => {
    cy.get("main")
      .find('button[aria-controls^="share-"]')
      .should("have.length.greaterThan", 4)
      .each(($header) =>
        expect($header.attr("aria-expanded"), "row starts closed").to.equal(
          "false",
        ),
      );
    cy.contains("Nothing open").should("be.visible");

    cy.contains("button", "Expand all").click();
    cy.get("main")
      .find('button[aria-controls^="share-"]')
      .each(($header) =>
        expect($header.attr("aria-expanded"), "row opened").to.equal("true"),
      );

    cy.contains("button", "Collapse all").click();
    cy.get('button[aria-controls="share-widget"]').should(
      "have.attr",
      "aria-expanded",
      "false",
    );
  });

  it("opens and closes one row without touching the others", () => {
    cy.get('button[aria-controls="share-widget"]').click();
    cy.get('button[aria-controls="share-widget"]').should(
      "have.attr",
      "aria-expanded",
      "true",
    );
    cy.get('button[aria-controls="share-api"]').should(
      "have.attr",
      "aria-expanded",
      "false",
    );

    cy.get('button[aria-controls="share-widget"]').click();
    cy.get('button[aria-controls="share-widget"]').should(
      "have.attr",
      "aria-expanded",
      "false",
    );
    cy.contains("Embed snippet").should("not.exist");
  });

  it("summarises what people will get, linked back to Settings", () => {
    openRow("answers");
    [
      "Shows the SQL",
      "Follow-up questions",
      "Charts",
      "Remembers context",
    ].forEach((chip) => cy.contains(chip).should("be.visible"));

    cy.contains("button", "Change").click();
    cy.location("pathname").should("contain", "/settings");
    cy.location("search").should("match", /agentId=.+/);
  });

  it("offers the chat bubble with its embed snippet and domain list", () => {
    // Name and switch are readable with the row shut; the snippet is not.
    cy.contains("Chat bubble on your website").should("be.visible");
    cy.get('[role="switch"][aria-label="Enable the chat bubble"]').should(
      "exist",
    );

    openRow("widget");
    cy.contains("Embed snippet").should("be.visible");
    cy.get("main").contains("agent.js").should("be.visible");
    cy.get("main").contains("data-agent-id").should("be.visible");
  });

  it("offers the full-page link, its iframe embed and an Open action", () => {
    cy.contains("Full-page chat link").should("be.visible");
    cy.get('[role="switch"][aria-label="Enable the full-page link"]').should(
      "exist",
    );

    openRow("fullpage");
    cy.contains("Shareable link").scrollIntoView().should("be.visible");
    cy.get("main")
      .contains(/mode=fullscreen/)
      .should("be.visible");
    cy.contains("Iframe embed").should("be.visible");
    cy.get('a:contains("Open")')
      .should("have.attr", "href")
      .and("match", /mode=fullscreen/);
  });

  it("adds and removes an allowed domain in the draft", () => {
    openRow("widget");
    const domain = `cypress-${Date.now()}.example.com`;
    cy.get('input[aria-label="Domain to allow"]').first().type(domain, {
      delay: 0,
    });
    cy.contains("button", "Add").first().click();
    cy.contains(domain).should("be.visible");

    cy.get(`button[aria-label="Remove ${domain}"]`).first().click();
    cy.contains(domain).should("not.exist");
    cy.contains("All domains allowed").should("be.visible");
  });

  it("warns that a switched-off bubble will not load anywhere", () => {
    openRow("widget");
    cy.get('[role="switch"][aria-label="Enable the chat bubble"]').then(
      ($toggle) => {
        const on = $toggle.attr("aria-checked") === "true";
        if (on) {
          cy.wrap($toggle).click();
          cy.contains("The bubble is switched off").should("be.visible");
          cy.wrap($toggle).click();
          cy.contains("The bubble is switched off").should("not.exist");
        } else {
          cy.contains("The bubble is switched off").should("be.visible");
        }
      },
    );
  });

  it("keeps the channel switch out of the disclosure it sits on", () => {
    // The switch is a sibling of the header button, never a child of it, so
    // enabling a channel cannot expand its row.
    openRow("widget");
    cy.get('button[aria-controls="share-widget"]').click();
    cy.get('[role="switch"][aria-label="Enable the chat bubble"]').then(
      ($toggle) => {
        cy.wrap($toggle).click();
        cy.get('button[aria-controls="share-widget"]').should(
          "have.attr",
          "aria-expanded",
          "false",
        );
        cy.wrap($toggle).click();
      },
    );
  });

  it("switches the API snippet between Python, JavaScript and cURL", () => {
    openRow("api");
    cy.get('[role="tablist"][aria-label="API language"]').should("exist");

    cy.get('[role="tablist"][aria-label="API language"]')
      .contains("Python")
      .click();
    cy.get("main").contains("import requests").should("be.visible");

    cy.get('[role="tablist"][aria-label="API language"]')
      .contains("JavaScript")
      .click();
    cy.get("main").contains("await fetch").should("be.visible");

    cy.get('[role="tablist"][aria-label="API language"]')
      .contains("cURL")
      .click();
    cy.get("main").contains("curl -X POST").should("be.visible");
  });

  it("lists the API keys it has, without issuing a new one", () => {
    cy.wait("@apiKeys");
    // Generating a key is this row's primary action, so it is reachable with
    // the row shut.
    cy.contains("button", "Generate API key")
      .scrollIntoView()
      .should("be.visible");

    openRow("api");
    cy.get("main").should(($main) => {
      const text = $main.text();
      expect(
        /No keys yet\./.test(text) || /created \d{2} \w{3} \d{4}/.test(text),
        "the key list rendered either its rows or its empty state",
      ).to.be.true;
    });
  });

  it("shows the people list with an invite field, without inviting anyone", () => {
    cy.contains("People").scrollIntoView().should("be.visible");
    // The count is on the closed row, so "who has access" needs no click.
    cy.get("main")
      .contains(/\d+ (people|person)/)
      .should("be.visible");

    // Invite someone opens the row and puts the caret in the email field.
    cy.contains("button", "Invite someone").click();
    cy.get('input[aria-label="Email to invite"]')
      .should("be.visible")
      .and("be.focused");
    cy.contains("button", "Invite").should("be.visible");
  });

  describe("appearance", () => {
    beforeEach(() => {
      openRow("appearance");
    });

    it("seeds the heading, sub heading and greeting from the agent", () => {
      cy.get("#apHead").invoke("val").should("not.be.empty");
      cy.get("#apSub").should(
        "have.value",
        "Query your database using natural language",
      );
      cy.get("#apGreet").invoke("val").should("not.be.empty");
    });

    it("edits the heading and Reset puts it back", () => {
      cy.get("#apHead")
        .invoke("val")
        .then((original) => {
          cy.get("#apHead").clear().type("Cypress heading", { delay: 0 });
          cy.get("#apHead").should("have.value", "Cypress heading");
          cy.contains("button", "Reset").click();
          cy.get("#apHead").should("have.value", original);
        });
    });

    it("mirrors the heading into the live preview", () => {
      cy.get("#apHead").clear().type("Cypress preview heading", { delay: 0 });
      openRow("preview");
      // The preview column is sticky, so the mirrored heading can sit outside
      // the viewport until it is scrolled to.
      cy.contains("Cypress preview heading")
        .scrollIntoView()
        .should("be.visible");
      cy.contains("button", "Reset").click();
    });

    it("picks a brand colour, a launcher icon and a chat avatar", () => {
      cy.get('button[aria-label="Brand colour #7C3AED"]').click();
      cy.get('button[aria-label="Brand colour #7C3AED"]').should(
        "have.attr",
        "aria-pressed",
        "true",
      );
      cy.get('button[aria-label="Icon 2"]').click();
      cy.get('button[aria-label="Icon 2"]').should(
        "have.attr",
        "aria-pressed",
        "true",
      );
      cy.get('button[aria-label="Avatar 2"]').click();
      cy.get('button[aria-label="Avatar 2"]').should(
        "have.attr",
        "aria-pressed",
        "true",
      );
      cy.contains("button", "Reset").click();
    });

    it("switches the preview between bubble and full page", () => {
      // The preview's mode control sits on its closed row, like every other
      // primary control on this screen.
      cy.get('[role="tablist"][aria-label="Preview mode"]').within(() => {
        cy.contains("Full page").click();
        cy.contains("Full page").should("have.attr", "aria-selected", "true");
        cy.contains("Bubble").click();
        cy.contains("Bubble").should("have.attr", "aria-selected", "true");
      });
    });

    it("keeps Save appearance available without pressing it", () => {
      cy.contains("button", "Save appearance")
        .scrollIntoView()
        .should("be.visible")
        .and("be.enabled");
    });
  });
});
