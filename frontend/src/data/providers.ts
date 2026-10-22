"use client";

import { useQuery } from "@tanstack/react-query";

import axios from "@/platform/utils/axios";

import { APIS } from "./api";

/**
 * The providers and models the NL2SQL service supports, from `GET /v1/models`.
 *
 * Node configuration used to offer a list written into the app, which drifts
 * the moment a model is added or retired — the service knows, so it is asked.
 */

interface WireProvider {
  provider_name: string;
  models: Array<{ model_name: string }>;
  default_model?: string;
}

export interface ProviderOption {
  provider: string;
  models: string[];
  defaultModel?: string;
}

export function useProviders() {
  return useQuery({
    queryKey: ["providers"],
    staleTime: 60 * 60 * 1000,
    queryFn: async (): Promise<ProviderOption[]> => {
      const response = await axios.get<{
        providers?: WireProvider[];
        models?: Array<{ provider?: string; name?: string; model?: string }>;
      }>(APIS.NL2SQL_MODELS);
      if (response.data.providers?.length) {
        return response.data.providers.map((provider) => ({
          provider: provider.provider_name,
          models: (provider.models ?? []).map((model) => model.model_name),
          defaultModel: provider.default_model,
        }));
      }

      const grouped = new Map<string, string[]>();
      for (const model of response.data.models ?? []) {
        const provider = model.provider ?? "openai";
        const name = model.name ?? model.model;
        if (name)
          grouped.set(provider, [...(grouped.get(provider) ?? []), name]);
      }
      return [...grouped].map(([provider, models]) => ({
        provider,
        models,
        defaultModel: models[0],
      }));
    },
  });
}
