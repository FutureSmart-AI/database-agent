import CredentialsView from "@/components/credentials/CredentialsView";
import AppShell from "@/components/shell/AppShell";

/**
 * Credentials — this product's own screen, on the NL2SQL service's own routes.
 *
 * Provider keys are workspace-wide, not per-agent: the same key the agent
 * dashboard stores is the one an NL2SQL agent answers with. The agent
 * dashboard's own page used to be mounted here, which kept one screen to
 * maintain but left this product looking like a detour through somebody else's
 * dashboard. What is shared now is the request layer instead —
 * `@/platform/lib/api-keys/api` already takes its routes as an argument, so both
 * products call the same fetchers, the same response normalisation and the same
 * 422-vs-502 error wording, and only the screen differs.
 *
 * The endpoints are this service's: credentials live on the NL2SQL service at
 * `/nl2sql/api/v1/owners/…` rather than the usage service's
 * `/api/usage/v1/owners/…`, with the same request and response bodies.
 *
 * `owner_id` is the literal `me`: the service resolves it from the session
 * cookie, so this page never has to wait for the viewer's email to load.
 *
 * Workspace-level, like Usage: it passes no agent, so the shell shows neither
 * the agent chip nor the agent-scoped rail.
 */
export default function CredentialsPage() {
  return (
    <AppShell title="Add Credentials">
      <CredentialsView />
    </AppShell>
  );
}
