"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { buildApiUrl } from "@/platform/utils";
import axios from "@/platform/utils/axios";

import { APIS } from "./api";
import type { Person } from "./types";

/**
 * Collaborators belong to the NL2SQL agent, not the chat registry.
 */

export function usePeople(
  agentId: string | undefined,
  owner: string | undefined,
) {
  return useQuery({
    queryKey: ["people", agentId],
    enabled: Boolean(agentId),
    queryFn: async (): Promise<Person[]> => {
      const url = buildApiUrl(APIS.NL2SQL_INVITATIONS, {
        agent_id: agentId as string,
      });
      const response = await axios.get<{
        invited_users?: Array<{
          email: string;
          role: "editor" | "viewer";
          invited_at?: string;
        }>;
      }>(url);
      return [
        ...(owner ? [{ email: owner, role: "owner" as const, since: "" }] : []),
        ...(response.data.invited_users ?? []).map((person) => ({
          email: person.email,
          role: person.role,
          since: person.invited_at ?? "",
        })),
      ];
    },
  });
}

export function usePeopleMutations(agentId: string | undefined) {
  const client = useQueryClient();
  const invalidate = () =>
    client.invalidateQueries({ queryKey: ["people", agentId] });

  const invite = useMutation({
    mutationFn: async (input: { email: string; role: "editor" | "viewer" }) => {
      const url = buildApiUrl(APIS.NL2SQL_INVITATIONS, {
        agent_id: agentId as string,
      });
      const response = await axios.post<{
        failed_emails?: string[];
        failures?: Array<{ email?: string; reason?: string }>;
      }>(url, { invitations: [input] });
      // The service answers 201 even when every address failed, so the two
      // failure lists are what decides success. `failures` carries the reason
      // and `failed_emails` the addresses; either alone means this did not
      // work, and reading only one would report a save that never happened.
      const { failed_emails = [], failures = [] } = response.data ?? {};
      if (!failed_emails.length && !failures.length) return;
      const reasons = failures
        .map((failure) => failure.reason)
        .filter(Boolean)
        .join(", ");
      throw new Error(
        reasons ||
          `${failed_emails.join(", ") || input.email} was not invited.`,
      );
    },
    onSuccess: invalidate,
  });

  const setRole = useMutation({
    mutationFn: async (input: { email: string; role: "editor" | "viewer" }) => {
      const url = buildApiUrl(APIS.NL2SQL_INVITATION, {
        agent_id: agentId as string,
        email: encodeURIComponent(input.email),
      });
      await axios.patch(url, { role: input.role });
    },
    onSuccess: invalidate,
  });

  const remove = useMutation({
    mutationFn: async (email: string) => {
      const url = buildApiUrl(APIS.NL2SQL_INVITATION, {
        agent_id: agentId as string,
        email: encodeURIComponent(email),
      });
      await axios.delete(url);
    },
    onSuccess: invalidate,
  });

  return { invite, setRole, remove };
}
