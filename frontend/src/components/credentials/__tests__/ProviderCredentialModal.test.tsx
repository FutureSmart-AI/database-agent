import type { ReactNode } from "react";

import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/platform/components/ToastContext";

import ProviderCredentialModal from "../ProviderCredentialModal";

/**
 * The add/edit dialog on the credentials screen.
 *
 * The design keeps one dialog for both, opened from the board: on edit the
 * provider is fixed, because on this service the provider *is* the credential's
 * identity, and a provider that already has a key is shown disabled rather than
 * dropped from the list — so it is obvious why it is missing and where the
 * existing key lives.
 */

const credentials = vi.hoisted(() => ({ data: [] as unknown[] }));
const save = vi.hoisted(() => ({ mutate: vi.fn(), isPending: false }));
const providers = vi.hoisted(() => ({
  data: [] as string[],
  isLoading: false,
}));

vi.mock("@/data/credentials", () => ({
  useOwnerCredentials: () => credentials,
  useCredentialProviders: () => providers,
  useSaveCredential: () => save,
}));
vi.mock("@/lib/fonts", () => ({ NL2SQL_FONT_CLASS: "font-test" }));

const wrapped = (node: ReactNode) =>
  render(<ToastProvider>{node}</ToastProvider>);

beforeEach(() => {
  credentials.data = [
    {
      provider: "openai",
      mask: "sk-...48sA",
      is_valid: true,
      updated_at: "2026-08-20T10:00:00+00:00",
    },
  ];
  providers.data = ["openai", "anthropic", "groq"];
  providers.isLoading = false;
  save.mutate.mockReset();
});

describe("ProviderCredentialModal", () => {
  it("asks for a provider service and a key, in the design's words", () => {
    wrapped(<ProviderCredentialModal onClose={() => {}} />);

    expect(screen.getByText("Add New Credential")).toBeTruthy();
    expect(
      screen.getByText("Enter your provider credentials securely below."),
    ).toBeTruthy();
    expect(screen.getByLabelText(/Provider Service/)).toBeTruthy();
  });

  it("disables a provider that already has a key, and says where it lives", () => {
    wrapped(<ProviderCredentialModal onClose={() => {}} />);

    const taken = screen.getByRole("option", {
      name: "OpenAI — already added, edit it in the board",
    }) as HTMLOptionElement;
    expect(taken.disabled).toBe(true);

    // One without a key stays selectable.
    const free = screen.getByRole("option", {
      name: "Anthropic",
    }) as HTMLOptionElement;
    expect(free.disabled).toBe(false);
  });

  it("fixes the provider when editing, because it identifies the credential", () => {
    wrapped(
      <ProviderCredentialModal onClose={() => {}} replaceProvider="openai" />,
    );

    expect(screen.getByText("Edit credential — OpenAI")).toBeTruthy();
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.getByText(/cannot be changed here/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Save changes" })).toBeTruthy();
  });

  it("refuses to save over a provider that already has a key", async () => {
    // The disabled option is hard to reach with a mouse, but a keyboard or a
    // stale render still can — the guard is what holds "one key per provider",
    // and this service's save endpoint would otherwise overwrite silently.
    wrapped(<ProviderCredentialModal onClose={() => {}} />);

    // `selectOptions` will not touch a disabled option, which is the point —
    // the value can still arrive by a route the pointer cannot take.
    const select = screen.getByLabelText(/Provider Service/);
    fireEvent.change(select, { target: { value: "openai" } });
    fireEvent.change(screen.getByLabelText(/API key/), {
      target: { value: "sk-test-key-1234" },
    });
    await userEvent.click(
      screen.getByRole("button", { name: "Add Credential" }),
    );

    expect(
      await screen.findByText(
        "OpenAI already has a key here — edit that one instead.",
      ),
    ).toBeTruthy();
    expect(save.mutate).not.toHaveBeenCalled();
  });
});
