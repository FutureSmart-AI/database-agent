import { describe, expect, it, vi } from "vitest";

import { toShare } from "../agents";

vi.mock("@/platform/utils/axios", () => ({ default: {} }));

describe("toShare", () => {
  it("reads the four service fields the Share screen writes", () => {
    expect(
      toShare({
        is_public: true,
        allowed_domains: ["acme.com", "*.acme.com"],
        fullscreen_is_public: true,
        fullscreen_allowed_domains: ["portal.acme.com"],
      }),
    ).toEqual({
      widget: true,
      fullpage: true,
      domains: ["acme.com", "*.acme.com"],
      fullscreenDomains: ["portal.acme.com"],
      keys: [],
    });
  });

  /**
   * `GET /agents` omits all four, so an agent row maps to "off, anywhere" —
   * which is why the Share screen seeds from `…/config?fields=agent_params`
   * instead and only falls back to this while that is still loading.
   */
  it("is off with no domains when the params carry none", () => {
    expect(toShare({})).toEqual({
      widget: false,
      fullpage: false,
      domains: [],
      fullscreenDomains: [],
      keys: [],
    });
  });

  it("keeps the two allowlists apart", () => {
    const share = toShare({
      allowed_domains: ["bubble.example"],
      fullscreen_allowed_domains: ["fullpage.example"],
    });
    expect(share.domains).toEqual(["bubble.example"]);
    expect(share.fullscreenDomains).toEqual(["fullpage.example"]);
  });
});
