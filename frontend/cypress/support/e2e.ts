import "./commands";

/**
 * Noise that is not a product defect.
 *
 * The Next dev server reports hydration mismatches and ResizeObserver loop
 * warnings as window errors, and axios rejections for a backend the spec is
 * deliberately not asserting on surface the same way. Failing a run on those
 * would report a broken suite rather than broken code — anything else is
 * rethrown so a genuine runtime error still fails the test.
 */
const IGNORED = [
  /ResizeObserver loop/i,
  /Hydration failed/i,
  /There was an error while hydrating/i,
  /Minified React error #(418|423|425)/,
  /NEXT_REDIRECT/,
  /Network Error/i,
  /Request aborted/i,
  /canceled/i,
  // Next's dev-only render instrumentation, which trips over its own clock on a
  // server-side `redirect()` — see /dashboard/usage/providers.
  /Failed to execute 'measure' on 'Performance'/,
];

Cypress.on("uncaught:exception", (error) =>
  IGNORED.some((pattern) => pattern.test(error.message)) ? false : undefined,
);
