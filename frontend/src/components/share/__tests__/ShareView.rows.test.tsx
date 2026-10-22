import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Agent } from "@/data/types";

/**
 * The Share screen's disclosure rows, at screen level.
 *
 * The data hooks are mocked because none of them is what is under test here:
 * what is under test is that the screen opens with every feature collapsed,
 * that a closed row still carries its name, purpose and primary control, and
 * that the two primary actions which live inside a body (issuing a key,
 * inviting someone) open their row rather than acting invisibly.
 */

const toast = { success: vi.fn(), error: vi.fn() };
const push = vi.fn();
const createKey = vi
  .fn()
  .mockResolvedValue({ key: { id: "k1" }, secret: "fsk_live_secret" });
const saveParams = vi.fn().mockResolvedValue({});
const refetchParams = vi.fn().mockResolvedValue({});

vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/platform/components/ToastContext", () => ({
  useToast: () => ({ toast }),
}));

const agent = {
  agent_id: "AG_1",
  service_ref: "NL2SQL_1",
  owner: "owner@futuresmart.ai",
  name: "Ecommerce Orders",
  feats: {
    show_sources: true,
    follow_up: true,
    chart_output: true,
    memory: false,
    global_memory: false,
    raw_response: false,
    voice_input: false,
    voice_output: false,
  },
  appearance: {
    heading: "Order Assistant",
    sub: "Query your database using natural language",
    greet: "Hello!",
    color: "#4f46e5",
    show_sources: true,
    icon: 0,
    avatar: 0,
  },
  share: {
    widget: true,
    fullpage: false,
    domains: ["acme-retail.com"],
    fullscreenDomains: [],
    keys: [],
  },
  dbs: [],
} as unknown as Agent;

vi.mock("@/data/useAgents", () => ({
  useAgent: () => ({ agent, isLoading: false, error: null }),
  useAgentParams: () => ({ data: undefined, refetch: refetchParams }),
}));
vi.mock("@/data/keys", () => ({
  useApiKeys: () => ({ data: [] }),
  useApiKeyMutations: () => ({
    create: { mutateAsync: createKey },
    revoke: { mutateAsync: vi.fn() },
  }),
}));
vi.mock("@/data/people", () => ({
  usePeople: () => ({
    data: [
      { email: "owner@futuresmart.ai", role: "owner", since: null },
      { email: "analyst@acme-retail.com", role: "viewer", since: null },
    ],
  }),
  usePeopleMutations: () => ({
    invite: { mutateAsync: vi.fn() },
    setRole: { mutateAsync: vi.fn() },
    remove: { mutateAsync: vi.fn() },
  }),
}));
vi.mock("@/data/widgetSettings", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/data/widgetSettings")>()),
  useWidgetSettings: () => ({
    settings: { data: undefined },
    icons: { data: [] },
    avatars: { data: [] },
    save: { mutateAsync: vi.fn() },
    reset: { mutateAsync: vi.fn() },
  }),
}));
vi.mock("@/data/mutations", () => ({
  useAgentMutations: () => ({ saveParams: { mutateAsync: saveParams } }),
}));
// Activity reads the session store; this screen's tests only care that the tab
// mounts it, so the store is stubbed empty.
vi.mock("@/data/conversations", () => ({
  useSessions: () => ({ data: [], isLoading: false, error: null }),
  useSessionTurns: () => ({ data: [], isLoading: false, error: null }),
}));
vi.mock("@/data/shareActivity", () => ({
  useActivityQueries: () => ({
    data: { rows: [], truncated: false },
    isLoading: false,
    isError: false,
    error: null,
  }),
}));

const { default: ShareView } = await import("../ShareView");

const header = (row: string) =>
  document.querySelector<HTMLButtonElement>(
    `button[aria-controls="share-${row}"]`,
  );

beforeEach(() => {
  vi.clearAllMocks();
  createKey.mockResolvedValue({ key: { id: "k1" }, secret: "fsk_live_secret" });
  saveParams.mockResolvedValue({});
  refetchParams.mockResolvedValue({});
});

describe("Share screen rows", () => {
  it("opens with every feature collapsed and none of the bodies rendered", () => {
    render(<ShareView agentId="AG_1" />);
    const headers = document.querySelectorAll(
      'button[aria-controls^="share-"]',
    );
    expect(headers).toHaveLength(7);
    headers.forEach((row) =>
      expect(row.getAttribute("aria-expanded")).toBe("false"),
    );
    expect(screen.getByText("Nothing open")).toBeInTheDocument();
    // Bodies belong to closed rows, so none of their content exists yet.
    expect(screen.queryByText("Embed snippet")).toBeNull();
    expect(document.querySelector("#apHead")).toBeNull();
  });

  it("says what each closed row is, and what state it is in", () => {
    render(<ShareView agentId="AG_1" />);
    expect(
      screen.getByText(/one script tag, a bubble in the corner/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/who you invited, and what each can do · 2 people/i),
    ).toBeInTheDocument();
    // The channel state pills read off the same flags as their switches.
    expect(
      within(header("widget")!.parentElement!).getByText("Live"),
    ).toBeInTheDocument();
    expect(
      within(header("fullpage")!.parentElement!).getByText("Off"),
    ).toBeInTheDocument();
    // The appearance row carries the heading people will actually read.
    expect(screen.getByText("Order Assistant")).toBeInTheDocument();
  });

  it("opens one row without opening its neighbours", async () => {
    render(<ShareView agentId="AG_1" />);
    await userEvent.click(header("widget")!);
    expect(header("widget")).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Embed snippet")).toBeInTheDocument();
    expect(header("fullpage")).toHaveAttribute("aria-expanded", "false");
    expect(header("api")).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText("1 open")).toBeInTheDocument();
  });

  it("expands and collapses all seven from the toolbar", async () => {
    render(<ShareView agentId="AG_1" />);
    await userEvent.click(screen.getByRole("button", { name: "Expand all" }));
    document
      .querySelectorAll('button[aria-controls^="share-"]')
      .forEach((row) => expect(row.getAttribute("aria-expanded")).toBe("true"));
    expect(screen.getByText("7 open")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Collapse all" }));
    document
      .querySelectorAll('button[aria-controls^="share-"]')
      .forEach((row) =>
        expect(row.getAttribute("aria-expanded")).toBe("false"),
      );
    expect(screen.getByText("Nothing open")).toBeInTheDocument();
  });

  it("does not expand the channel row when its switch is flipped", async () => {
    render(<ShareView agentId="AG_1" />);
    await userEvent.click(
      screen.getByRole("switch", { name: "Enable the chat bubble" }),
    );
    expect(header("widget")).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Embed snippet")).toBeNull();
  });

  it("issues a key from the closed API row and opens it so the key is visible", async () => {
    render(<ShareView agentId="AG_1" />);
    // The action is reachable without opening the row…
    const generate = screen.getByRole("button", { name: /generate api key/i });
    expect(header("api")).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(generate);
    expect(createKey).toHaveBeenCalledTimes(1);
    // …and the row it lands in opens, rather than the key arriving unseen.
    await waitFor(() =>
      expect(header("api")).toHaveAttribute("aria-expanded", "true"),
    );
  });

  it("opens the People row and focuses the invite field from its header action", async () => {
    render(<ShareView agentId="AG_1" />);
    await userEvent.click(
      screen.getByRole("button", { name: /invite someone/i }),
    );
    expect(header("people")).toHaveAttribute("aria-expanded", "true");
    const field = screen.getByLabelText("Email to invite");
    await waitFor(() => expect(field).toHaveFocus());
  });

  it("keeps Change navigating to Settings from the closed row", async () => {
    render(<ShareView agentId="AG_1" />);
    await userEvent.click(screen.getByRole("button", { name: "Change" }));
    expect(push).toHaveBeenCalledTimes(1);
    expect(String(push.mock.calls[0][0])).toContain("settings");
  });
});

describe("Share rows under change", () => {
  it("keeps an open row open when its own switch is flipped", async () => {
    render(<ShareView agentId="AG_1" />);
    await userEvent.click(header("widget")!);
    await userEvent.click(
      screen.getByRole("switch", { name: "Enable the chat bubble" }),
    );
    await waitFor(() => expect(saveParams).toHaveBeenCalledTimes(1));
    expect(header("widget")).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Embed snippet")).toBeInTheDocument();
  });

  it("puts the row's state pill back when the service refuses the change", async () => {
    saveParams.mockRejectedValueOnce(new Error("nope"));
    render(<ShareView agentId="AG_1" />);
    const row = () => within(header("widget")!.parentElement!);
    expect(row().getByText("Live")).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("switch", { name: "Enable the chat bubble" }),
    );
    // Draft moved first, so the pill said Off — and the refusal must undo both.
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    await waitFor(() => expect(row().getByText("Live")).toBeInTheDocument());
  });

  it("closes one row out of an expanded set without disturbing the rest", async () => {
    render(<ShareView agentId="AG_1" />);
    await userEvent.click(screen.getByRole("button", { name: "Expand all" }));
    await userEvent.click(header("api")!);
    expect(header("api")).toHaveAttribute("aria-expanded", "false");
    expect(header("widget")).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("6 open")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Expand all" }),
    ).toBeInTheDocument();
  });

  it("ends closed after a double-click on the header", async () => {
    render(<ShareView agentId="AG_1" />);
    await userEvent.dblClick(header("widget")!);
    expect(header("widget")).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Embed snippet")).toBeNull();
  });

  it("opens a row from the keyboard", async () => {
    render(<ShareView agentId="AG_1" />);
    header("answers")!.focus();
    await userEvent.keyboard("{Enter}");
    expect(header("answers")).toHaveAttribute("aria-expanded", "true");
    await userEvent.keyboard(" ");
    expect(header("answers")).toHaveAttribute("aria-expanded", "false");
    // Focus stays on the header it was on, so the next row is one Tab away.
    expect(header("answers")).toHaveFocus();
  });

  it("edits the appearance draft from the closed row and shows it on the row", async () => {
    render(<ShareView agentId="AG_1" />);
    await userEvent.click(header("appearance")!);
    const heading = screen.getByLabelText(/heading/i, { selector: "#apHead" });
    await userEvent.clear(heading);
    await userEvent.type(heading, "Orders desk");
    // The row's own pill is what says which heading is live while it is shut.
    await userEvent.click(header("appearance")!);
    expect(screen.getByText("Orders desk")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Reset" }));
    expect(screen.getByText("Order Assistant")).toBeInTheDocument();
  });

  it("switches the preview mode from the closed row and keeps it on open", async () => {
    render(<ShareView agentId="AG_1" />);
    const modes = screen.getByRole("tablist", { name: "Preview mode" });
    await userEvent.click(
      within(modes).getByRole("tab", { name: "Full page" }),
    );
    expect(
      within(modes).getByRole("tab", { name: "Full page" }),
    ).toHaveAttribute("aria-selected", "true");
    await userEvent.click(header("preview")!);
    expect(
      within(modes).getByRole("tab", { name: "Full page" }),
    ).toHaveAttribute("aria-selected", "true");
  });

  it("does not open the API row when the key could not be issued", async () => {
    createKey.mockRejectedValueOnce(new Error("quota"));
    render(<ShareView agentId="AG_1" />);
    await userEvent.click(
      screen.getByRole("button", { name: /generate api key/i }),
    );
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(header("api")).toHaveAttribute("aria-expanded", "false");
  });
});

describe("Share sections", () => {
  it("opens on Set up, with Activity one tab away", () => {
    render(<ShareView agentId="AG_1" />);
    const tabs = screen.getByRole("tablist", { name: "Share sections" });
    expect(within(tabs).getByRole("tab", { name: "Set up" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(within(tabs).getByRole("tab", { name: "Activity" })).toHaveAttribute(
      "aria-selected",
      "false",
    );
  });

  it("swaps the rows for what other people asked, and back", async () => {
    render(<ShareView agentId="AG_1" />);
    await userEvent.click(screen.getByRole("tab", { name: "Activity" }));
    // Set up is gone rather than merely scrolled past.
    expect(
      document.querySelector('button[aria-controls="share-widget"]'),
    ).toBeNull();
    expect(
      screen.getByRole("tablist", { name: "Activity source" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Nothing shared yet")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("tab", { name: "Set up" }));
    expect(header("widget")).toHaveAttribute("aria-expanded", "false");
  });

  it("keeps which rows were open across a trip to Activity", async () => {
    render(<ShareView agentId="AG_1" />);
    await userEvent.click(header("widget")!);
    await userEvent.click(screen.getByRole("tab", { name: "Activity" }));
    await userEvent.click(screen.getByRole("tab", { name: "Set up" }));
    expect(header("widget")).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Embed snippet")).toBeInTheDocument();
  });
});
