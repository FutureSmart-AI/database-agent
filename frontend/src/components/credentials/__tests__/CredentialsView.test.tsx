import type { ReactNode } from "react";

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/platform/components/ToastContext";

import CredentialsView from "../CredentialsView";

/**
 * The credentials board.
 *
 * The rows below are the shape `GET /v1/owners/{owner_id}/credentials` actually
 * answers with — `{ provider, mask, is_valid, updated_at }`, captured live on
 * 2026-08-23. There is no `created_at` and no plaintext key in it, which is why
 * the table has an Updated column and no reveal control; a fixture that invented
 * either would let those columns back in.
 */

const credentials = vi.hoisted(() => ({
  data: [] as unknown[],
  isLoading: false,
}));
const providers = vi.hoisted(() => ({
  data: [] as string[],
  isLoading: false,
}));
const remove = vi.hoisted(() => ({ mutate: vi.fn(), isPending: false }));

vi.mock("@/data/credentials", () => ({
  useOwnerCredentials: () => credentials,
  useCredentialProviders: () => providers,
  useDeleteCredential: () => remove,
  useSaveCredential: () => ({ mutate: vi.fn(), isPending: false }),
}));

vi.mock("@/lib/fonts", () => ({ NL2SQL_FONT_CLASS: "font-test" }));

const wrapped = (node: ReactNode) =>
  render(<ToastProvider>{node}</ToastProvider>);

const ROWS = [
  {
    provider: "openai",
    mask: "sk-...48sA",
    is_valid: true,
    updated_at: "2026-08-20T10:00:00+00:00",
  },
  {
    provider: "deepseek",
    mask: "sk-...9zz1",
    is_valid: false,
    updated_at: "2026-08-22T10:00:00+00:00",
  },
];

beforeEach(() => {
  credentials.data = [];
  credentials.isLoading = false;
  providers.data = [
    "openai",
    "anthropic",
    "groq",
    "google",
    "deepseek",
    "minimax",
  ];
  providers.isLoading = false;
  remove.mutate.mockReset();
});

describe("CredentialsView", () => {
  it("counts keys, answer providers, and anything that is not one", () => {
    credentials.data = ROWS;
    wrapped(<CredentialsView />);

    const stat = (label: string) =>
      screen.getByText(label).parentElement?.textContent ?? "";
    expect(stat("Active keys")).toContain("2");
    // Both stored providers are on the service's own answer-provider list.
    expect(stat("LLM providers")).toContain("2");
    // Nothing left over — this service stores answer-model keys only.
    expect(stat("Tools configured")).toContain("0");
  });

  it("counts a stored provider the service no longer offers as a tool", () => {
    // The formula is "everything that is not an answer provider", so a
    // credential for something outside that list is not silently uncounted.
    credentials.data = [
      ...ROWS,
      {
        provider: "langsmith",
        mask: "lsv2...42",
        is_valid: true,
        updated_at: "2026-08-23T10:00:00+00:00",
      },
    ];
    wrapped(<CredentialsView />);
    const stat = (label: string) =>
      screen.getByText(label).parentElement?.textContent ?? "";
    expect(stat("Active keys")).toContain("3");
    expect(stat("Tools configured")).toContain("1");
  });

  it("names providers the way a reader writes them, not as wire ids", () => {
    credentials.data = ROWS;
    wrapped(<CredentialsView />);
    expect(screen.getByText("OpenAI")).toBeTruthy();
    expect(screen.getByText("DeepSeek")).toBeTruthy();
    expect(screen.queryByText("openai")).toBeNull();
  });

  it("masks a key until the eye is clicked, then shows the mask only", async () => {
    credentials.data = ROWS;
    wrapped(<CredentialsView />);

    // Dots by default — not even the last four.
    expect(screen.queryByText("sk-...48sA")).toBeNull();

    const eye = screen.getByRole("button", { name: "Show the OpenAI key" });
    // The tooltip does not promise a key: the service never sends one back.
    expect(eye.getAttribute("title")).toContain("never sent back");
    await userEvent.click(eye);

    expect(screen.getByText("sk-...48sA")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Hide the OpenAI key" }),
    ).toBeTruthy();
  });

  it("flags only a key the provider has stopped accepting", () => {
    credentials.data = ROWS;
    wrapped(<CredentialsView />);
    // One row is `is_valid: false`; the other says nothing, because this
    // service refuses to store a key the provider rejects — "verified" on
    // every row would be a badge that carries no information.
    expect(screen.getByText("Provider rejected it")).toBeTruthy();
    expect(screen.queryByText("Verified")).toBeNull();
  });

  it("stamps the date the way the design does, with the relative age on hover", () => {
    credentials.data = [ROWS[0]];
    wrapped(<CredentialsView />);
    // "20 Aug 2026, 10:00" — an absolute stamp, not "3d ago".
    expect(screen.getByText(/20 Aug 2026/)).toBeTruthy();
  });

  it("has the four columns the design has — no state column", () => {
    credentials.data = ROWS;
    wrapped(<CredentialsView />);
    expect(
      screen.getAllByRole("columnheader").map((th) => th.textContent?.trim()),
    ).toEqual(["Provider", "API key", "Updated", "Actions"]);
  });

  it("sorts newest first and flips on a second click", async () => {
    credentials.data = ROWS;
    wrapped(<CredentialsView />);

    const providerCell = () =>
      within(screen.getAllByRole("row")[1]).getByText(/OpenAI|DeepSeek/)
        .textContent;
    // deepseek was updated later, so it leads.
    expect(providerCell()).toBe("DeepSeek");

    await userEvent.click(screen.getByRole("button", { name: /Updated/ }));
    expect(providerCell()).toBe("OpenAI");
  });

  it("offers edit and delete as icon actions, named for screen readers", () => {
    credentials.data = ROWS;
    wrapped(<CredentialsView />);

    // Icon-only, as the artifact draws them — so the name has to live in the
    // accessible label rather than in visible text.
    expect(
      screen.getByRole("button", { name: "Edit the OpenAI credential" }),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Delete the OpenAI credential" }),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Replace" })).toBeNull();
  });

  it("asks before deleting, and deletes by provider", async () => {
    credentials.data = ROWS;
    wrapped(<CredentialsView />);

    await userEvent.click(
      screen.getByRole("button", {
        name: "Delete the DeepSeek credential",
      }),
    );
    expect(screen.getByText(/cannot be recovered/)).toBeTruthy();
    expect(remove.mutate).not.toHaveBeenCalled();

    await userEvent.click(
      screen.getByRole("button", { name: "Delete credential" }),
    );
    // The provider *is* the credential's identity on this service.
    expect(remove.mutate.mock.calls[0][0]).toBe("deepseek");
  });

  it("closes the delete dialog when the service says the key is already gone", async () => {
    // The documented answer for a key that is not there is a 404, "No
    // credential stored for that provider" — the row was stale, so the dialog
    // has nothing left to confirm.
    credentials.data = ROWS;
    remove.mutate.mockImplementation(
      (_provider: string, opts: { onError: (error: unknown) => void }) =>
        opts.onError({
          isAxiosError: true,
          response: {
            status: 404,
            data: { detail: "No credential stored for that provider" },
          },
        }),
    );
    wrapped(<CredentialsView />);

    await userEvent.click(
      screen.getByRole("button", { name: "Delete the OpenAI credential" }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Delete credential" }),
    );

    expect(
      await screen.findByText("No credential stored for that provider"),
    ).toBeTruthy();
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: "Delete credential" }),
      ).toBeNull(),
    );
  });

  it("says what to do when nothing is stored", () => {
    credentials.data = [];
    wrapped(<CredentialsView />);
    expect(screen.getByText("No API keys configured yet")).toBeTruthy();
    // The design's empty state points at the one control in the header rather
    // than repeating it inside the card.
    expect(
      screen.getByText(/Click "Add New Credentials" to get started/),
    ).toBeTruthy();
    expect(
      screen.getAllByRole("button", { name: /Add New Credentials/ }),
    ).toHaveLength(1);
  });

  it("orders by the date column alone, as the design's header does", () => {
    credentials.data = ROWS;
    wrapped(<CredentialsView />);

    // One sortable header in the design (`data-credsort="created"`); Provider is
    // a plain label there, so it is a plain label here.
    expect(
      screen
        .getAllByRole("columnheader")
        .filter((th) => th.querySelector("button")),
    ).toHaveLength(1);
    expect(
      screen.queryByRole("button", { name: /Sort by Provider/ }),
    ).toBeNull();
  });

  it("titles the card the way the design does, with no count beside it", () => {
    credentials.data = ROWS;
    wrapped(<CredentialsView />);

    expect(screen.getByText("Configured Providers")).toBeTruthy();
    expect(screen.getByText("every key on this account")).toBeTruthy();
    // The design's card header carries a title and a note — nothing else.
    expect(screen.queryByText(/stored$/)).toBeNull();
  });
});
