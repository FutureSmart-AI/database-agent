import { defineConfig } from "cypress";

import { registerRunReport } from "./cypress/support/report";

/**
 * Two suites:
 *
 * - `cypress/e2e/smoke/**` stubs the whole backend (`support/stubs.ts`) and
 *   needs no session. It is what CI runs, against the static export
 *   (`bun run preview`), and it proves the app builds, mounts, routes, forwards
 *   the retired `/nl2sql/*` URLs and paints every screen.
 * - `cypress/e2e/nl2sql/**` talks to a real NL2SQL backend, so each spec is
 *   gated on `E2E_AUTHENTICATED=1` and reports as pending — not failed —
 *   without one. Run it against a signed-in origin, i.e. `bun run dev:secure`
 *   (see docs/configuration.md):
 *
 *     E2E_BASE_URL=https://local.futuresmart.ai:4443 bun run test:e2e:live
 *
 * `E2E_NL2SQL_AGENT_ID` pins the agent the agent-scoped specs open. Left unset,
 * the suite resolves the first NL2SQL agent in the workspace once and reuses it.
 * The full-lifecycle journey (`cypress/e2e/nl2sql/00-full-journey.cy.ts`)
 * additionally needs real, read-only database credentials — see `E2E_DB_*`
 * below and `cypress/README.md`.
 */
export default defineConfig({
  e2e: {
    baseUrl: process.env.E2E_BASE_URL || "http://localhost:3001",
    specPattern: "cypress/e2e/**/*.cy.ts",
    supportFile: "cypress/support/e2e.ts",
    fixturesFolder: "cypress/fixtures",
    videosFolder: "cypress/videos",
    screenshotsFolder: "cypress/screenshots",
    video: false,
    screenshotOnRunFailure: true,
    // The dashboard fans out a request per agent on Home and streams chat
    // answers over SSE; the defaults are tuned for a stubbed app, not for a
    // real backend behind a proxy.
    defaultCommandTimeout: 15000,
    requestTimeout: 20000,
    responseTimeout: 60000,
    pageLoadTimeout: 90000,
    retries: { runMode: 2, openMode: 0 },
    viewportWidth: 1440,
    viewportHeight: 900,
    experimentalRunAllSpecs: true,
    setupNodeEvents(on) {
      registerRunReport(on, process.cwd());
    },
  },
  env: {
    // Gates every spec that needs a real session and backend.
    E2E_AUTHENTICATED: process.env.E2E_AUTHENTICATED ?? "",
    // Opt-in for the specs that ask a real question of a real database.
    E2E_ASK: process.env.E2E_ASK ?? "",
    NL2SQL_AGENT_ID: process.env.E2E_NL2SQL_AGENT_ID ?? "",

    // Where the journey's own cleanup requests go. The app calls
    // `/nl2sql/api/*` on its own origin (the dev server or the CDN routes it),
    // so by default that is the base URL too.
    API_BASE:
      process.env.E2E_API_BASE ??
      process.env.E2E_BASE_URL ??
      "http://localhost:3001",

    // The database the lifecycle journey connects its throwaway agent to.
    // Use a read-only user — the journey only ever reads.
    DB_ENGINE: process.env.E2E_DB_ENGINE ?? "postgresql",
    DB_HOST: process.env.E2E_DB_HOST ?? "",
    DB_PORT: process.env.E2E_DB_PORT ?? "",
    DB_NAME: process.env.E2E_DB_NAME ?? "",
    DB_USER: process.env.E2E_DB_USER ?? "",
    DB_PASSWORD: process.env.E2E_DB_PASSWORD ?? "",
    DB_DESCRIPTION: process.env.E2E_DB_DESCRIPTION ?? "",
    // The question the journey asks. Pick one whose answer is a small set of
    // labelled numbers, so the agent charts it.
    ASK_QUERY: process.env.E2E_ASK_QUERY ?? "",
  },
});
