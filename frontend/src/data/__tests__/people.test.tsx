import type { ReactNode } from "react";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import axios from "@/platform/utils/axios";

import { usePeopleMutations } from "../people";

vi.mock("@/platform/utils/axios", () => ({
  default: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

const mockedPost = vi.mocked(axios.post);
const mockedPatch = vi.mocked(axios.patch);
const mockedDelete = vi.mocked(axios.delete);

const AGENT = "NL2SQL_E5DC283F";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const mutations = () =>
  renderHook(() => usePeopleMutations(AGENT), { wrapper }).result;

describe("usePeopleMutations", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedPost.mockResolvedValue({ data: { invited_users: [{}] } });
    mockedPatch.mockResolvedValue({ data: {} });
    mockedDelete.mockResolvedValue({ data: {} });
  });

  it("invites with the chosen role", async () => {
    await mutations().current.invite.mutateAsync({
      email: "person@example.com",
      role: "editor",
    });

    expect(mockedPost).toHaveBeenCalledWith(
      `/nl2sql/api/v1/agents/${AGENT}/invitations`,
      { invitations: [{ email: "person@example.com", role: "editor" }] },
    );
  });

  // The service answers 201 even when every address failed, so the failure
  // lists are what decides success.
  it("fails on a reason in `failures`", async () => {
    mockedPost.mockResolvedValue({
      data: {
        failed_emails: ["bad@x.com"],
        failures: [{ email: "bad@x.com", reason: "Invalid role 'admin'." }],
      },
    });

    await expect(
      mutations().current.invite.mutateAsync({
        email: "bad@x.com",
        role: "viewer",
      }),
    ).rejects.toThrow("Invalid role 'admin'.");
  });

  // `failed_emails` can arrive without a matching reason — reading only
  // `failures` would report an invitation that was never created.
  it("fails on `failed_emails` alone", async () => {
    mockedPost.mockResolvedValue({
      data: { failed_emails: ["bad@x.com"], failures: [] },
    });

    await expect(
      mutations().current.invite.mutateAsync({
        email: "bad@x.com",
        role: "viewer",
      }),
    ).rejects.toThrow("bad@x.com was not invited.");
  });

  it("URL-encodes the email in the path once", async () => {
    await mutations().current.setRole.mutateAsync({
      email: "person@example.com",
      role: "viewer",
    });
    await mutations().current.remove.mutateAsync("person@example.com");

    const path = `/nl2sql/api/v1/agents/${AGENT}/invitations/person%40example.com`;
    expect(mockedPatch).toHaveBeenCalledWith(path, { role: "viewer" });
    expect(mockedDelete).toHaveBeenCalledWith(path);
  });
});
