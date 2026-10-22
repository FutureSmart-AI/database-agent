/** What a provider's key is used for, in this product's own terms. */
export const PROVIDER_NOTE =
  "Used for every node this workspace's agents run on.";

/**
 * How a provider's id is spelled for a reader.
 *
 * The service answers with wire identifiers — `openai`, `deepseek` — and those
 * are not names anyone writes down. This map is presentation only: a provider
 * the service adds tomorrow still appears, title-cased by `providerLabel`, so
 * nothing here gates which providers the screen can show.
 */
const PROVIDER_LABELS: Record<string, string> = {
  openai: "OpenAI",
  anthropic: "Anthropic",
  groq: "Groq",
  google: "Google",
  gemini: "Google (Gemini)",
  deepseek: "DeepSeek",
  minimax: "MiniMax",
  // What the key is for, not just whose it is: the design spells both of its
  // tool providers this way, because "LangSmith" alone does not say why a key
  // for it sits on this screen.
  langsmith: "LangSmith (tracing)",
  aws: "AWS (RDS discovery)",
};

export function providerLabel(provider: string): string {
  return (
    PROVIDER_LABELS[provider.toLowerCase()] ??
    provider.charAt(0).toUpperCase() + provider.slice(1)
  );
}

/**
 * The shortest key the service will store.
 *
 * `CredentialAddRequest.api_key` is `minLength: 8`, and a shorter one is a 422
 * from the endpoint rather than a message about the key itself — so the form
 * says so before it sends. Verified live on 2026-08-23: `"short"` answered
 * `string_too_short`.
 */
export const MIN_API_KEY_LENGTH = 8;
