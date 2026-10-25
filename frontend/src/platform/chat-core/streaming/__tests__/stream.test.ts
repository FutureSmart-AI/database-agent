import { afterEach, describe, expect, it, vi } from "vitest";

import { streamSSERequest } from "../stream";

/**
 * A refused question comes back as an error body, not a stream. Its `detail` is
 * either a sentence or `{code, message, …}` — a used-up free allowance names
 * its case that way — and the reader must see the sentence in both shapes,
 * never "[object Object]" or a generic fallback.
 */
function refuse(status: number, detail: unknown) {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ detail }), { status })),
  );
}

async function errorFor(status: number, detail: unknown) {
  refuse(status, detail);
  const onError = vi.fn();
  await streamSSERequest({
    url: "/nl2sql/api/v1/agents/A/chat?stream=true",
    onEvent: vi.fn(),
    onComplete: vi.fn(),
    onError,
  });
  return onError.mock.calls[0][0];
}

afterEach(() => vi.unstubAllGlobals());

describe("streamSSERequest — refused questions", () => {
  it("carries a sentence detail through as a quota error", async () => {
    const error = await errorFor(429, "Query limit reached: 20 of 20.");
    expect(error).toMatchObject({
      type: "quota",
      message: "Query limit reached: 20 of 20.",
    });
  });

  it("reads the message out of a structured detail", async () => {
    const error = await errorFor(429, {
      code: "demo_allowance_exhausted",
      reason: "total",
      message:
        "You have used all 20 free sample-data questions on this account.",
    });
    expect(error).toMatchObject({
      type: "quota",
      message:
        "You have used all 20 free sample-data questions on this account.",
    });
  });
});
