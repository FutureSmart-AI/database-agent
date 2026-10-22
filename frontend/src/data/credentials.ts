"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";

import {
  addCredentials,
  deleteCredentials,
  fetchOwnerCredentials,
  fetchProviders,
  type ApiKeysApis,
  type OwnerCredential,
} from "@/platform/lib/api-keys/api";

import { APIS } from "./api";

/**
 * The workspace's provider keys, on the NL2SQL service's own routes.
 *
 * The request layer is the agent dashboard's — those functions already take the
 * routes as an argument, precisely so a second product can point them at its own
 * service without a second copy of the fetching, the response normalisation or
 * the 422-vs-502 error wording. What this product owns is the screen.
 *
 * `owner_id` is the literal `me`: the service resolves the owner from the session
 * cookie, so nothing here waits on the viewer's email to load.
 */

const OWNER_ID = "me";

const CREDENTIAL_APIS: ApiKeysApis = {
  GET_PROVIDERS: APIS.OWNER_PROVIDERS,
  GET_CREDENTIALS: APIS.OWNER_CREDENTIALS,
  ADD_CREDENTIALS: APIS.OWNER_CREDENTIALS,
  DELETE_CREDENTIALS: APIS.OWNER_CREDENTIAL,
};

export type { OwnerCredential };

/**
 * Providers a key can be stored for.
 *
 * Read from the service rather than listed in the app, so a provider added
 * server-side needs no frontend release. NL2SQL answers with `llm_providers`
 * only — it has no document-parsing or web-scraping path — and deliberately
 * omits `gemini`, which is stored as `google`.
 */
export function useCredentialProviders() {
  return useQuery({
    queryKey: ["credential-providers", APIS.OWNER_PROVIDERS],
    queryFn: async () => {
      const data = await fetchProviders({ apis: CREDENTIAL_APIS });
      return (
        data.llm_providers ??
        (data.providers ?? []).map((entry) => entry.provider)
      );
    },
  });
}

/** Which providers this owner has a key for — masked, never the key itself. */
export function useOwnerCredentials() {
  return useQuery({
    queryKey: ["owner-credentials", APIS.OWNER_CREDENTIALS, OWNER_ID],
    queryFn: async (): Promise<OwnerCredential[]> => {
      const response = await fetchOwnerCredentials(OWNER_ID, {
        apis: CREDENTIAL_APIS,
      });
      return response.data ?? [];
    },
  });
}

function useInvalidateCredentials() {
  const client = useQueryClient();
  return () =>
    client.invalidateQueries({
      queryKey: ["owner-credentials", APIS.OWNER_CREDENTIALS, OWNER_ID],
    });
}

/**
 * Store a key, or replace the one already held for that provider.
 *
 * There is no separate update call: an owner has at most one key per provider,
 * so posting the same provider again replaces it. The service validates the key
 * with the provider first and stores nothing if it is rejected, which is why the
 * caller keeps its dialog open on failure rather than reporting a save.
 */
export function useSaveCredential() {
  const invalidate = useInvalidateCredentials();

  return useMutation({
    mutationFn: (payload: { provider: string; api_key: string }) =>
      addCredentials(OWNER_ID, payload, { apis: CREDENTIAL_APIS }),
    onSuccess: () => invalidate(),
  });
}

/**
 * Remove an owner's key for one provider.
 *
 * A hard delete — the ciphertext stops existing. Their usage falls back to the
 * platform key from the next call onward.
 */
export function useDeleteCredential() {
  const invalidate = useInvalidateCredentials();

  return useMutation({
    mutationFn: (provider: string) =>
      deleteCredentials(OWNER_ID, provider, { apis: CREDENTIAL_APIS }),
    onSuccess: () => invalidate(),
    /**
     * A 404 — "No credential stored for that provider" — is the documented
     * answer for a key that is not there, which means the row on screen is
     * stale rather than the delete having failed. Re-reading the list is what
     * makes that row go away; without it, it sits there and every retry 404s
     * again.
     */
    onError: (error: unknown) => {
      if (isAxiosError(error) && error.response?.status === 404) invalidate();
    },
  });
}
