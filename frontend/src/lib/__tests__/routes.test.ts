import { afterEach, describe, expect, it, vi } from "vitest";

import { publicApiRoot } from "../routes";

/**
 * The API examples on the Share page name `publicApiRoot()`. Production sets it
 * to the canonical `https://futuresmart.ai/database-agent/api`; any other build
 * names its own `/nl2sql/api`, so staging never hands out production URLs.
 */
describe("publicApiRoot", () => {
  afterEach(() => vi.unstubAllEnvs());

  it("uses the configured canonical root, without a trailing slash", () => {
    vi.stubEnv(
      "NEXT_PUBLIC_PUBLIC_API_ROOT",
      "https://futuresmart.ai/database-agent/api/",
    );
    expect(publicApiRoot()).toBe("https://futuresmart.ai/database-agent/api");
  });

  it("falls back to the public host's /nl2sql/api", () => {
    vi.stubEnv("NEXT_PUBLIC_PUBLIC_API_ROOT", "");
    vi.stubEnv("NEXT_PUBLIC_PUBLIC_HOST", "https://staging.example.test");
    expect(publicApiRoot()).toBe("https://staging.example.test/nl2sql/api");
  });

  it("falls back to the page's own origin when nothing is configured", () => {
    vi.stubEnv("NEXT_PUBLIC_PUBLIC_API_ROOT", "");
    vi.stubEnv("NEXT_PUBLIC_PUBLIC_HOST", "");
    expect(publicApiRoot()).toBe(`${window.location.origin}/nl2sql/api`);
  });
});
