"use client";

import { type ReactNode } from "react";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";

import type { Profile as AgentProfile } from "@/platform/components/rag/dashboard/auth-types";
import { AuthContext } from "@/platform/components/rag/dashboard/AuthContext";
import type { IAgent, IService } from "@/platform/types/agent";
import { buildApiUrl } from "@/platform/utils";
import axios from "@/platform/utils/axios";

import { fetchAgent } from "./agents";
import { APIS } from "./api";
import { useSession } from "./session";

/**
 * Lets this product mount the agent UI's own components.
 *
 * Anything reused from `src/components` — the whole conversations stack, the
 * profile menu — reads its agent and viewer from the agent UI's `AuthContext`.
 * Rather than fork those components, this supplies that context from what this
 * app already has: the session from `./session` and the agent in `?agentId=`.
 *
 * It deliberately does **not** use the agent UI's `AuthProvider`, which owns
 * login redirects, session-expiry countdowns and the `?agent_id=` parameter —
 * this product handles all of that itself (see `RequireSession`), and mounting
 * both would give two components the same job.
 */

/** A minimal NL2SQL agent shaped for the shared chat components. */
function useSelectedAgent(agentId: string | null) {
  return useQuery<IAgent | null>({
    queryKey: ["selectedAgent", agentId],
    enabled: Boolean(agentId),
    refetchOnWindowFocus: false,
    // An id this account cannot see answers 403 or 404, which retrying cannot
    // change — and a query left in an error state holds no data, so every
    // consumer that mounts asks again. Resolving to null caches the answer.
    retry: false,
    staleTime: 5 * 60 * 1000,
    queryFn: async () => {
      try {
        const agent = await fetchAgent(agentId as string);
        return {
          agent_id: agent.agent_id,
          owner_id: agent.owner,
          services: [
            {
              service_type: "nl2sql",
              service_id: agent.agent_id,
              status: "enabled",
            },
          ],
          config: { agent_params: { agent_name: agent.name } },
        } as IAgent;
      } catch (error) {
        const status = isAxiosError(error) ? error.response?.status : undefined;
        if (status === 403 || status === 404) return null;
        throw error;
      }
    },
  });
}

/**
 * The caller's role on this agent — owner when they own it, otherwise whatever
 * the invitation says. Same derivation the agent UI uses, so a viewer sees the
 * same read-only chat here as there.
 */
function useUserRole(agent: IAgent | null, email: string | undefined) {
  return useQuery<"owner" | "editor" | "viewer" | null>({
    queryKey: ["userRole", agent?.agent_id, email],
    enabled: Boolean(agent && email),
    retry: false,
    refetchOnWindowFocus: false,
    queryFn: async () => {
      if (!agent || !email) return null;
      if (agent.owner_id === email) return "owner";
      const url = buildApiUrl(APIS.NL2SQL_INVITATIONS, {
        agent_id: agent.agent_id,
      });
      const response = await axios.get<{
        invited_users?: Array<{ email: string; role: "editor" | "viewer" }>;
      }>(url);
      return (
        response.data.invited_users?.find(
          (invitation) =>
            invitation.email.toLowerCase() === email.toLowerCase(),
        )?.role ?? null
      );
    },
  });
}

const serviceId = (agent: IAgent | null, type: string): string | null =>
  agent?.services?.find((service: IService) => service.service_type === type)
    ?.service_id ?? null;

const serviceEnabled = (agent: IAgent | null, type: string): boolean =>
  agent?.services?.find((service: IService) => service.service_type === type)
    ?.status === "enabled";

export default function AuthBridge({
  agentId,
  children,
}: {
  /** The agent this subtree is scoped to, from `?agentId=`. */
  agentId?: string;
  children: ReactNode;
}) {
  const { profile } = useSession();
  const client = useQueryClient();
  const id = agentId ?? null;

  const agentQuery = useSelectedAgent(id);
  const agent = agentQuery.data ?? null;
  const roleQuery = useUserRole(agent, profile?.email);
  const userRole = roleQuery.data ?? null;

  return (
    <AuthContext.Provider
      value={{
        // The agent UI's `Profile` carries session bookkeeping this product does
        // not use; the fields its components read are the identity ones.
        profile: (profile as unknown as AgentProfile) ?? null,
        selectedAgent: agent,
        agentId: id,
        knowledgeId: serviceId(agent, "knowledge"),
        isKnowledgeEnabled: serviceEnabled(agent, "knowledge"),
        refetchSelectedAgent: () => {
          client.invalidateQueries({ queryKey: ["selectedAgent", id] });
        },
        isNl2sqlEnabled: serviceEnabled(agent, "nl2sql"),
        nl2sqlId: serviceId(agent, "nl2sql"),
        actionsServiceIds: [],
        integrationServiceIds: [],
        userRole,
        // Until the role resolves, assume the least access rather than the most:
        // guessing owner would briefly show a viewer the editing controls.
        isOwner: userRole === "owner",
        isEditor: userRole === "editor",
        isViewer: userRole === "viewer",
        // Session expiry is owned by this product's own session handling.
        sessionExpiresAt: null,
        stayLoggedIn: () => Promise.resolve(false),
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}
