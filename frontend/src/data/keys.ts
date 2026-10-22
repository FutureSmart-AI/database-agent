"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { buildApiUrl } from "@/platform/utils";
import axios from "@/platform/utils/axios";

import { APIS } from "./api";
import type { ApiKey } from "./types";

/**
 * API keys, from the NL2SQL service's own routes:
 *
 * - `GET    /nl2sql/api/v1/agents/{agent_id}/api-keys`
 * - `POST   /nl2sql/api/v1/agents/{agent_id}/api-keys`
 * - `DELETE /nl2sql/api/v1/agents/{agent_id}/api-keys/{api_key}`
 *
 * Not the dashboard service: those routes are keyed by chat-registry ids and
 * answer 403 for an `NL2SQL_…` agent, so this page listed nothing and could
 * neither issue nor revoke a key.
 *
 * The listing returns each key in full to the caller who owns it, so the view
 * can offer Copy and a reveal toggle. A revoked key stays in the list with
 * `is_active: false` and a `revoked_at` timestamp.
 */

interface WireKey {
  api_key?: string;
  agent_id?: string;
  user_id?: string | null;
  created_at?: string | null;
  revoked_at?: string | null;
  is_active?: boolean;
  /** Older dashboard-shaped rows; kept so a masked-only response still lists. */
  masked_key?: string;
  key_id?: string;
}

/** `sk-abc…xyz` → `sk-abc********` — the form the list shows by default. */
function mask(key: string): string {
  if (!key) return "";
  return `${key.slice(0, 4)}${"*".repeat(Math.max(4, Math.min(8, key.length - 4)))}`;
}

function toKey(row: WireKey): ApiKey {
  const secret = row.api_key ?? null;
  const masked = row.masked_key ?? (secret ? mask(secret) : "");
  return {
    id: row.key_id ?? secret ?? masked,
    masked,
    secret,
    created: row.created_at ? Date.parse(row.created_at) : 0,
    // Absent means the endpoint did not report one, and the key is usable.
    active: row.is_active ?? !row.revoked_at,
  };
}

export function useApiKeys(agentId: string | undefined) {
  return useQuery({
    queryKey: ["api-keys", agentId],
    enabled: Boolean(agentId),
    queryFn: async (): Promise<ApiKey[]> => {
      const url = buildApiUrl(APIS.API_KEYS, { agent_id: agentId as string });
      const response = await axios.get<{ api_keys: WireKey[] }>(url);
      return (response.data.api_keys ?? []).map(toKey);
    },
  });
}

export function useApiKeyMutations(agentId: string | undefined) {
  const client = useQueryClient();
  const invalidate = () =>
    client.invalidateQueries({ queryKey: ["api-keys", agentId] });

  const create = useMutation({
    mutationFn: async (): Promise<{ key: ApiKey; secret: string }> => {
      const url = buildApiUrl(APIS.API_KEYS, { agent_id: agentId as string });
      // The body is optional: `user_id` is only for master-key callers, and a
      // signed-in caller is resolved from the session.
      const response = await axios.post<WireKey>(url, {});
      return {
        key: toKey(response.data),
        secret: response.data.api_key ?? "",
      };
    },
    onSuccess: invalidate,
  });

  const revoke = useMutation({
    mutationFn: async (apiKey: string) => {
      const url = buildApiUrl(APIS.API_KEY, {
        agent_id: agentId as string,
        api_key: apiKey,
      });
      await axios.delete(url);
    },
    onSuccess: invalidate,
  });

  return { create, revoke };
}
