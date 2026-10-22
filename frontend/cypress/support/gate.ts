/**
 * The same opt-in gate the Playwright suite uses (`E2E_AUTHENTICATED`).
 *
 * Every spec in this suite drives the real backend through the dev proxy, and
 * the proxy only carries a session after `bun dev` has done the SSO handshake.
 * Without one the pages sit on their loading state forever, so a gated spec is
 * reported as *pending* instead of failing — a fresh clone, and CI, stay green
 * without pretending the coverage ran.
 *
 *   bun dev
 *   CYPRESS_E2E_AUTHENTICATED=1 bun run test:cy
 */
export const isAuthenticated = (): boolean =>
  Boolean(Cypress.env("E2E_AUTHENTICATED"));

/** `describe` when a session is available, `describe.skip` when it is not. */
export const describeAuthed: Mocha.SuiteFunction = (
  isAuthenticated() ? describe : describe.skip
) as Mocha.SuiteFunction;

/** Same gate, plus an extra environment variable a spec cannot run without. */
export const describeWithEnv = (name: string): Mocha.SuiteFunction =>
  (isAuthenticated() && Cypress.env(name)
    ? describe
    : describe.skip) as Mocha.SuiteFunction;
