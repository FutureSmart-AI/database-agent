import { isAxiosError } from "axios";

import type {
  CredentialAddRequest,
  CredentialAddResponse,
  CredentialDeleteResponse,
  CredentialListResponse,
  ProviderListResponse,
} from "@/platform/lib/usage/types";
import { buildApiUrl } from "@/platform/utils";
import axios from "@/platform/utils/axios";

/**
 * The four credential routes. There are no defaults: the agent UI's version of
 * this module fell back to the Usage service (`/api/usage/v1/owners/…`), and a
 * caller that forgot to pass its own routes quietly called the wrong service.
 * This product always passes the NL2SQL ones (`@/data/credentials`).
 */
export interface ApiKeysApis {
  GET_PROVIDERS: string;
  GET_CREDENTIALS: string;
  ADD_CREDENTIALS: string;
  DELETE_CREDENTIALS: string;
}

/** Which service to call, and an optional abort signal for the request. */
export interface CredentialRequestOptions {
  apis: ApiKeysApis;
  signal?: AbortSignal;
}

export interface Provider {
  provider: string;
  capabilities: string[];
}

/**
 * Owner credential with created_at for backward compatibility
 * Maps from CredentialData (which has updated_at)
 */
export interface OwnerCredential {
  provider: string;
  created_at?: string;
  mask?: string;
  is_valid?: boolean;
  updated_at?: string;
}

export interface ProvidersResponse {
  providers?: Provider[];
  llm_providers?: string[];
  document_and_web_providers?: string[];
}

/**
 * Credentials response - maps from CredentialListResponse
 */
export interface CredentialsResponse {
  data: OwnerCredential[];
}

export interface AddCredentialsRequest {
  provider: string;
  api_key: string;
}

/**
 * Substitutes `{owner_id}` — and `{provider}`, where the route has one.
 *
 * `buildApiUrl` infers which params a template needs from the placeholders in
 * its literal type, and a route supplied by a scope is a plain `string`, which
 * widens that inference to `never`. The cast names the one placeholder every
 * route here has; extra keys are substituted at runtime all the same. The
 * analytics hooks work around the same thing for their `{agent_id}` routes.
 */
const credentialUrl = (
  template: string,
  params: { owner_id: string; provider?: string },
): string =>
  buildApiUrl(
    template as "{owner_id}",
    params as unknown as Record<"owner_id", string>,
  );

/**
 * Get list of supported providers by capability
 * Handles both old format (providers array) and new format (llm_providers, document_and_web_providers)
 */
export async function fetchProviders({
  apis,
  signal,
}: CredentialRequestOptions): Promise<
  ProvidersResponse & ProviderListResponse
> {
  const response = await axios.get<ProviderListResponse>(apis.GET_PROVIDERS, {
    signal,
  });
  const data = response.data;

  // If response has the new format, normalize it to the old format for compatibility
  if (data.llm_providers || data.document_and_web_providers) {
    const providers: Provider[] = [];

    // Add LLM providers
    if (data.llm_providers) {
      data.llm_providers.forEach((provider) => {
        providers.push({
          provider,
          capabilities: ["llm"],
        });
      });
    }

    // Add document and web providers. NL2SQL has no document-parsing or
    // web-scraping path and stopped returning the field at all, which this
    // guard already covered.
    if (data.document_and_web_providers) {
      data.document_and_web_providers.forEach((provider) => {
        providers.push({
          provider,
          capabilities: ["tool", "document", "web"],
        });
      });
    }

    return {
      ...data,
      providers,
    };
  }

  return data as ProvidersResponse & ProviderListResponse;
}

/**
 * Get list of owner credentials
 */
export async function fetchOwnerCredentials(
  ownerId: string,
  { apis, signal }: CredentialRequestOptions,
): Promise<CredentialsResponse> {
  const url = credentialUrl(apis.GET_CREDENTIALS, { owner_id: ownerId });
  const response = await axios.get<CredentialListResponse>(url, { signal });

  // Transform CredentialListResponse to CredentialsResponse for backward compatibility
  const data = response.data;
  return {
    data: (data.data ?? []).map((cred) => ({
      provider: cred.provider,
      created_at: cred.updated_at, // Use updated_at as created_at for compatibility
      mask: cred.mask,
      is_valid: cred.is_valid,
      updated_at: cred.updated_at,
    })),
  };
}

/**
 * Add or replace API credentials.
 *
 * There is no separate update call: an owner has at most one key per provider,
 * so posting again for the same provider replaces the stored key. The service
 * calls the provider to check the key before storing it, which takes a second
 * or two — and rejects the whole request on a bad key, saving nothing.
 */
export async function addCredentials(
  ownerId: string,
  payload: CredentialAddRequest,
  { apis, signal }: CredentialRequestOptions,
): Promise<CredentialAddResponse> {
  const url = credentialUrl(apis.ADD_CREDENTIALS, { owner_id: ownerId });
  const response = await axios.post<CredentialAddResponse>(url, payload, {
    signal,
  });
  return response.data;
}

/**
 * Delete API credentials
 */
export async function deleteCredentials(
  ownerId: string,
  provider: string,
  { apis, signal }: CredentialRequestOptions,
): Promise<CredentialDeleteResponse> {
  const url = credentialUrl(apis.DELETE_CREDENTIALS, {
    owner_id: ownerId,
    provider,
  });
  const response = await axios.delete<CredentialDeleteResponse>(url, {
    signal,
  });
  return response.data;
}

/**
 * What to tell the user when storing or deleting a key fails.
 *
 * The distinction that matters is 422 from 502. A 422 is the provider itself
 * rejecting the key — nothing was saved, and the reason in `detail` is the only
 * thing that tells the user which key to look at. A 502 means we could not
 * reach the provider to check: the key may well be fine, so saying it is
 * invalid would be wrong.
 *
 * FastAPI answers body validation (an `api_key` under 8 characters) with
 * `detail` as a list of issues rather than a string, so both shapes are read.
 */
export function credentialErrorMessage(
  error: unknown,
  fallback: string,
): string {
  if (!isAxiosError(error)) return fallback;

  const status = error.response?.status;
  if (status === 502 || status === 503 || status === 504) {
    return "Couldn't verify the key just now — try again.";
  }

  const detail = (error.response?.data as { detail?: unknown } | undefined)
    ?.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((issue) =>
        typeof issue === "string"
          ? issue
          : ((issue as { msg?: string } | null)?.msg ?? ""),
      )
      .filter(Boolean);
    if (messages.length) return messages.join(". ");
  }

  return fallback;
}
