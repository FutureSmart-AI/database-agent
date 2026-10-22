import { describe, expect, it } from "vitest";

import { providerLabel } from "../constants";

/**
 * How a provider's wire id is spelled for a reader.
 *
 * The service answers with identifiers (`openai`, `langsmith`); the design draws
 * names. The two tool providers it lists say what they are for, because
 * "LangSmith" and "AWS" alone do not explain why a key for them is here.
 */
describe("providerLabel", () => {
  it("names the answer providers the way the design writes them", () => {
    expect(providerLabel("openai")).toBe("OpenAI");
    expect(providerLabel("deepseek")).toBe("DeepSeek");
    expect(providerLabel("minimax")).toBe("MiniMax");
  });

  it("says what a tool provider's key is for", () => {
    expect(providerLabel("langsmith")).toBe("LangSmith (tracing)");
    expect(providerLabel("aws")).toBe("AWS (RDS discovery)");
  });

  it("still shows a provider it has never heard of", () => {
    expect(providerLabel("cohere")).toBe("Cohere");
  });
});
