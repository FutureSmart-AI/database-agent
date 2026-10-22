/**
 * Where this app lives.
 *
 * The whole product sits under `/database-agent` — the workspace *is* the
 * product's entry point, so there is no marketing page above it and no
 * `/dashboard` segment below it. That holds in both of its mounts: compiled into
 * the agent UI, and as the standalone export served from
 * `app.futuresmart.ai/database-agent` (see the Product & Domain Architecture
 * doc). Every link goes through these constants, so one route tree serves both
 * and the two mounts cannot drift apart.
 */

/**
 * The host this product is served from, used for the share link and the embed
 * snippets people copy.
 *
 * The share link and the embed script are served by the chat widget, which
 * lives on `agent.futuresmart.ai`; production sets `NEXT_PUBLIC_PUBLIC_HOST` to
 * that host (see docs/configuration.md). With no override it is wherever the
 * page is actually being served from, so a staging build cannot hand out
 * production URLs.
 */
export function publicHost(): string {
  const configured = process.env.NEXT_PUBLIC_PUBLIC_HOST;
  if (configured) return configured.replace(/\/+$/, "");
  return typeof window === "undefined" ? "" : window.location.origin;
}

/** The product entry point. */
export const APP = "/database-agent";

/**
 * Where the product used to live, before it was renamed from NL2SQL to Database
 * Agent (ClickUp 86bbh7h9z).
 *
 * Kept as a constant because the retired paths are still served: the build is a
 * static export with no server to answer them with a 302, so every old URL has
 * a page whose only job is to forward. The internal service API is a different
 * matter and keeps this prefix for good — `/nl2sql/api/v1/…` is unchanged and
 * must stay that way.
 */
export const LEGACY_APP = "/nl2sql";

export const ROUTES = {
  home: APP,
  conversations: `${APP}/conversations`,
  analytics: `${APP}/analytics`,
  share: `${APP}/share`,
  reports: `${APP}/batch-query-reports`,
  settings: `${APP}/settings`,
  usage: `${APP}/usage`,
  credentials: `${APP}/credentials`,
} as const;

/** A product route with the agent it applies to. */
export function agentRoute(
  route: (typeof ROUTES)[keyof typeof ROUTES],
  agentId: string,
): string {
  return `${route}?agentId=${agentId}`;
}
