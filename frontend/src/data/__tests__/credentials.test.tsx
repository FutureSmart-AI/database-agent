import type { ReactNode } from "react";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { AxiosError, AxiosHeaders } from "axios";
import { beforeEach, describe, expect, it, vi } from "vitest";

import axios from "@/platform/utils/axios";

import {
  useCredentialProviders,
  useDeleteCredential,
  useOwnerCredentials,
  useSaveCredential,
} from "../credentials";

/**
 * The credentials calls, against the routes `nl2sql/api/docs` documents under
 * **Owner Credentials** and the bodies it answers with — all four verified live
 * on 2026-08-24 through the dev proxy:
 *
 * - `GET  /v1/owners/providers`                        → `{ llm_providers: [...] }` (no `gemini`, no document/web field)
 * - `GET  /v1/owners/{owner_id}/credentials`           → `{ status, data: [{ provider, mask, is_valid, updated_at }] }`
 * - `POST /v1/owners/{owner_id}/credentials`           → `{ status, data }`, or 422 with the provider's own reason
 * - `DELETE /v1/owners/{owner_id}/credentials/{prov}`  → `{ status, message }`, or **404** "No credential stored for that provider"
 *
 * `owner_id` is `me`; the service resolves the caller from the session cookie
 * (an email works there too, verified).
 */

vi.mock("@/platform/utils/axios", () => ({
  default: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
}));

const mockedGet = vi.mocked(axios.get);
const mockedPost = vi.mocked(axios.post);
const mockedDelete = vi.mocked(axios.delete);

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

/** A response the way this service actually answers a missing key. */
const notFound = () =>
  new AxiosError(
    "Request failed with status code 404",
    "ERR_BAD_REQUEST",
    {
      headers: new AxiosHeaders(),
    } as never,
    undefined,
    {
      status: 404,
      statusText: "Not Found",
      data: { detail: "No credential stored for that provider" },
      headers: {},
      config: { headers: new AxiosHeaders() } as never,
    },
  );

beforeEach(() => {
  mockedGet.mockReset();
  mockedPost.mockReset();
  mockedDelete.mockReset();
});

describe("data/credentials", () => {
  it("reads the providers off the documented route", async () => {
    mockedGet.mockResolvedValue({
      data: { llm_providers: ["openai", "anthropic", "groq"] },
    });

    const { result } = renderHook(() => useCredentialProviders(), { wrapper });
    await waitFor(() => expect(result.current.data).toBeTruthy());

    expect(mockedGet.mock.calls[0][0]).toBe("/nl2sql/api/v1/owners/providers");
    expect(result.current.data).toEqual(["openai", "anthropic", "groq"]);
  });

  it("lists this owner's keys as masks, from `data`", async () => {
    mockedGet.mockResolvedValue({
      data: {
        status: "success",
        data: [
          {
            provider: "openai",
            mask: "sk-...48sA",
            is_valid: true,
            updated_at: "2026-08-20T10:00:00+00:00",
          },
        ],
      },
    });

    const { result } = renderHook(() => useOwnerCredentials(), { wrapper });
    await waitFor(() => expect(result.current.data?.length).toBe(1));

    expect(mockedGet.mock.calls[0][0]).toBe(
      "/nl2sql/api/v1/owners/me/credentials",
    );
    expect(result.current.data?.[0].mask).toBe("sk-...48sA");
  });

  it("posts a key to the owner route, provider and api_key only", async () => {
    mockedPost.mockResolvedValue({
      data: {
        status: "success",
        data: {
          provider: "groq",
          mask: "gsk...9f2A",
          is_valid: true,
          updated_at: "2026-08-24T10:00:00+00:00",
        },
      },
    });

    const { result } = renderHook(() => useSaveCredential(), { wrapper });
    result.current.mutate({ provider: "groq", api_key: "gsk_realkey1234" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(mockedPost.mock.calls[0][0]).toBe(
      "/nl2sql/api/v1/owners/me/credentials",
    );
    expect(mockedPost.mock.calls[0][1]).toEqual({
      provider: "groq",
      api_key: "gsk_realkey1234",
    });
  });

  it("deletes by provider on the documented route", async () => {
    mockedDelete.mockResolvedValue({
      data: { status: "success", message: "Credential deleted" },
    });

    const { result } = renderHook(() => useDeleteCredential(), { wrapper });
    result.current.mutate("openai");
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(mockedDelete.mock.calls[0][0]).toBe(
      "/nl2sql/api/v1/owners/me/credentials/openai",
    );
  });

  it("re-reads the list when a delete answers 404 — the key is already gone", async () => {
    mockedGet.mockResolvedValue({
      data: {
        status: "success",
        data: [
          {
            provider: "openai",
            mask: "sk-...48sA",
            is_valid: true,
            updated_at: "2026-08-20T10:00:00+00:00",
          },
        ],
      },
    });
    mockedDelete.mockRejectedValue(notFound());

    const client = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    const wrap = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );

    const list = renderHook(() => useOwnerCredentials(), { wrapper: wrap });
    await waitFor(() => expect(list.result.current.data?.length).toBe(1));
    const reads = mockedGet.mock.calls.length;

    const { result } = renderHook(() => useDeleteCredential(), {
      wrapper: wrap,
    });
    result.current.mutate("openai");
    await waitFor(() => expect(result.current.isError).toBe(true));

    // A 404 means the row on screen is stale, not that nothing happened — the
    // list has to be re-read or the row sits there forever.
    await waitFor(() =>
      expect(mockedGet.mock.calls.length).toBeGreaterThan(reads),
    );
  });
});
