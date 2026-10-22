import { describeAuthed } from "../../support/gate";
import { API, ROUTES } from "../../support/routes";

/**
 * Settings → Answers and Settings → Advanced.
 *
 * Both tabs edit a draft of what the API returned and save it explicitly, so
 * the specs assert the draft behaviour and stop short of Save — a run must not
 * rewrite an agent's answer features or node models.
 */
describeAuthed("Database Agent · Settings → Answers", () => {
  beforeEach(() => {
    cy.intercept("GET", API.databases).as("databases");
    cy.visitAgent(ROUTES.settings);
    cy.wait("@databases");
    cy.tab("Answers");
  });

  it("seeds the agent name from the agent itself", () => {
    cy.get("#agName").invoke("val").should("not.be.empty");
  });

  it("lists every answer feature with its explanation", () => {
    // Only the features `AgentParamsRequest` on the NL2SQL service defines.
    // "Remember context", "Remember across conversations" and "Raw response"
    // were removed with the orchestration behaviour they described — see
    // `src/data/constants.ts`.
    const features: Array<[string, string]> = [
      ["Show sources", "Adds the executed SQL"],
      ["Follow-up questions", "Suggests the next questions"],
      ["Charts", "Draws a chart"],
    ];
    features.forEach(([title, hint]) => {
      cy.contains(title).should("be.visible");
      cy.contains(hint).should("be.visible");
    });
    [
      "Remember context",
      "Remember across conversations",
      "Raw response",
    ].forEach((gone) => {
      cy.get("main").contains(gone).should("not.exist");
    });
  });

  it("toggles a feature in the draft and back", () => {
    cy.contains("label", "Show sources")
      .find('input[type="checkbox"]')
      .then(($box) => {
        const before = $box.prop("checked") as boolean;
        cy.wrap($box).click();
        cy.wrap($box).should(before ? "not.be.checked" : "be.checked");
        cy.wrap($box).click();
        cy.wrap($box).should(before ? "be.checked" : "not.be.checked");
      });
  });

  it("explains the transcription language instead of offering a picker", () => {
    // The service has no `default_language` field, so a picker here would save
    // nothing. Voice input still toggles; the note replaces the dead control.
    cy.contains("label", "Enable Voice Input")
      .find('input[type="checkbox"]')
      .then(($box) => {
        const wasOn = $box.prop("checked") as boolean;
        if (!wasOn) cy.wrap($box).click();
        cy.get("#vLang").should("not.exist");
        cy.get("main")
          .contains("The language is detected from what is spoken")
          .should("be.visible");
        if (!wasOn) cy.wrap($box).click();
      });
  });

  it("adds and removes a suggested question in the draft", () => {
    cy.get("body").then(($body) => {
      const before = $body.find(
        'input[aria-label^="Suggested question "]',
      ).length;

      cy.contains("button", "Add Question").click();
      cy.get('input[aria-label^="Suggested question "]').should(
        "have.length",
        before + 1,
      );
      cy.get('input[aria-label^="Suggested question "]')
        .last()
        .type("How many orders shipped late last month?", { delay: 0 });

      cy.get('button[aria-label^="Remove suggested question "]').last().click();
      cy.get("body")
        .find('input[aria-label^="Suggested question "]')
        .should("have.length", before);
    });
  });

  it("keeps Save Changes available without pressing it", () => {
    // It sits below the fold of the scrolling view box, and Cypress only
    // auto-scrolls for actions, not for assertions.
    cy.contains("button", "Save Changes")
      .scrollIntoView()
      .should("be.visible")
      .and("be.enabled");
  });
});

describeAuthed("Database Agent · Settings → Advanced", () => {
  beforeEach(() => {
    cy.intercept("GET", API.databases).as("databases");
    cy.intercept("GET", API.nodes).as("nodes");
    cy.intercept("GET", API.providers).as("providers");
    cy.visitAgent(ROUTES.settings);
    cy.wait("@databases");
    cy.tab("Advanced");
    cy.wait("@nodes");
  });

  it("heads the section and lists the workflow nodes", () => {
    cy.get("main")
      .contains("h1", "Agent Node Configuration")
      .should("be.visible");
    cy.get("main").find("details").should("have.length.greaterThan", 0);
    cy.get("main").find("details summary").first().should("be.visible");
    cy.get("main")
      .contains(/^(default|changed)$/)
      .should("be.visible");
  });

  it("opens a node and shows its provider, model, temperature, tokens and prompt", () => {
    cy.get("main").find("details").first().find("summary").click();
    cy.get("main")
      .find("details")
      .first()
      .within(() => {
        cy.get('select[aria-label^="Provider for "]').should("be.visible");
        cy.get('select[aria-label^="Model for "]').should("be.visible");
        cy.get('input[aria-label^="Temperature for "]').should("be.visible");
        cy.get('input[aria-label^="Max tokens for "]').should("be.visible");
        cy.get('textarea[aria-label^="Prompt for "]').should("be.visible");
        cy.contains("button", "Reset to default").should("be.visible");
      });
  });

  it("marks a node as changed once its temperature is edited", () => {
    cy.get("main").find("details").first().find("summary").click();
    cy.get('input[aria-label^="Temperature for "]')
      .first()
      .clear()
      .type("0.7", { delay: 0 });
    cy.get("main")
      .find("details")
      .first()
      .find("summary")
      .should("contain.text", "changed");
  });

  it("keeps the save affordance and its warning without pressing it", () => {
    cy.contains("button", "Save node configuration")
      .scrollIntoView()
      .should("be.visible")
      .and("be.enabled");
    cy.contains(
      "Changes apply to the next question this agent is asked.",
    ).should("be.visible");
  });
});
