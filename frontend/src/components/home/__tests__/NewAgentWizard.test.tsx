import type { ReactNode } from "react";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AxiosError, AxiosHeaders } from "axios";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createNl2sqlAgent } from "@/data/agents";
import {
  addDatabase,
  generateDescription,
  testConnection,
} from "@/data/databases";
import type { AgentDatabase } from "@/data/types";
import { ToastProvider } from "@/platform/components/ToastContext";

import NewAgentWizard from "../NewAgentWizard";

/**
 * The manual-connection path of the new-agent wizard: every connection is
 * tested before an agent exists, the agent is created next, and only then are
 * its databases added. A failure at either of the first two steps must stop
 * the chain and say why.
 */

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/database-agent",
}));

vi.mock("@/data/agents", () => ({
  createNl2sqlAgent: vi.fn(),
  listRdsDatabases: vi.fn(),
}));
vi.mock("@/data/databases", () => ({
  addDatabase: vi.fn(),
  fetchDatabases: vi.fn(),
  generateDescription: vi.fn(),
  testConnection: vi.fn(),
}));
vi.mock("@/data/session", () => ({
  useOwnerId: () => "owner@example.com",
}));
// `next/font` only loads inside a Next build; the modal shell reads these
// classes at import time.
vi.mock("@/lib/fonts", () => ({ NL2SQL_FONT_CLASS: "font-test" }));

const OWNER = "owner@example.com";
const SERVICE_ID = "NL2SQL_TEST0001";

const expectedConnection = {
  db_name: "orders_prod",
  db_engine: "postgresql",
  db_host: "db.internal.acme.com",
  db_port: 5432,
  db_user: "analytics_ro",
  db_password: "s3cret",
  description: "",
};

const addedDatabase: AgentDatabase = {
  db_id: "db_1",
  db_name: "orders_prod",
  db_engine: "postgresql",
  db_host: "db.internal.acme.com",
  db_port: 5432,
  db_user: "analytics_ro",
  active: true,
  reachable: true,
  latency: null,
  description: "Live retail orders",
  description_status: "set",
  description_source: "manual",
  description_updated_at: null,
  table_count: 3,
  included_table_count: 3,
};

function renderWizard(node: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>{node}</ToastProvider>
    </QueryClientProvider>,
  );
}

/** Names the agent, moves to step 2 and fills the manual connection fields. */
async function fillAndSubmit() {
  const user = userEvent.setup();
  renderWizard(<NewAgentWizard onClose={() => {}} />);

  await user.type(
    screen.getByLabelText(/What should this agent be called/),
    "Ecommerce Orders",
  );
  await user.click(
    screen.getByRole("button", { name: "Next — connect a database" }),
  );

  expect(
    screen.getByRole("tab", { name: /Enter credentials/ }),
  ).toHaveAttribute("aria-selected", "true");

  await user.type(screen.getByLabelText(/^Host/), expectedConnection.db_host);
  await user.type(
    screen.getByLabelText(/^Database name/),
    expectedConnection.db_name,
  );
  await user.type(
    screen.getByLabelText(/^Username/),
    expectedConnection.db_user,
  );
  await user.type(
    screen.getByLabelText(/^Password/),
    expectedConnection.db_password,
  );

  await user.click(screen.getByRole("button", { name: "Test & create agent" }));
}

beforeEach(() => {
  vi.mocked(testConnection).mockReset();
  vi.mocked(createNl2sqlAgent).mockReset();
  vi.mocked(addDatabase).mockReset();
  vi.mocked(generateDescription).mockReset();
});

describe("NewAgentWizard — manual connection", () => {
  it("tests the connection, then creates the agent, then adds the database", async () => {
    vi.mocked(testConnection).mockResolvedValue({
      status: "connected",
      message: "ok",
    });
    vi.mocked(createNl2sqlAgent).mockResolvedValue({
      agent_id: SERVICE_ID,
      service_id: SERVICE_ID,
    });
    vi.mocked(addDatabase).mockResolvedValue(addedDatabase);

    await fillAndSubmit();

    expect(
      await screen.findByText(/Ecommerce Orders is ready/),
    ).toBeInTheDocument();

    expect(testConnection).toHaveBeenCalledTimes(1);
    expect(testConnection).toHaveBeenCalledWith(expectedConnection);
    expect(createNl2sqlAgent).toHaveBeenCalledTimes(1);
    expect(createNl2sqlAgent).toHaveBeenCalledWith({
      ownerId: OWNER,
      name: "Ecommerce Orders",
    });
    expect(addDatabase).toHaveBeenCalledTimes(1);
    expect(addDatabase).toHaveBeenCalledWith(SERVICE_ID, expectedConnection);

    const [testOrder] = vi.mocked(testConnection).mock.invocationCallOrder;
    const [createOrder] = vi.mocked(createNl2sqlAgent).mock.invocationCallOrder;
    const [addOrder] = vi.mocked(addDatabase).mock.invocationCallOrder;
    expect(testOrder).toBeLessThan(createOrder);
    expect(createOrder).toBeLessThan(addOrder);

    // The returned row already carries a description, so none is generated.
    expect(generateDescription).not.toHaveBeenCalled();
    expect(
      screen.queryByText("Could not create the agent"),
    ).not.toBeInTheDocument();
  });

  it("stops before creating an agent when the connection test fails", async () => {
    vi.mocked(testConnection).mockResolvedValue({
      status: "error",
      message: "password authentication failed",
    });

    await fillAndSubmit();

    expect(
      await screen.findByText("Could not create the agent"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/password authentication failed/),
    ).toBeInTheDocument();

    expect(testConnection).toHaveBeenCalledTimes(1);
    expect(createNl2sqlAgent).not.toHaveBeenCalled();
    expect(addDatabase).not.toHaveBeenCalled();
    expect(screen.queryByText(/is ready/)).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Back to the database details" }),
    ).toBeInTheDocument();
  });

  it("reports a failed agent create and never adds the database", async () => {
    vi.mocked(testConnection).mockResolvedValue({
      status: "connected",
      message: "ok",
    });
    vi.mocked(createNl2sqlAgent).mockRejectedValue(
      new AxiosError(
        "Request failed with status code 400",
        "ERR_BAD_REQUEST",
        undefined,
        undefined,
        {
          status: 400,
          statusText: "Bad Request",
          data: { detail: "Agent limit reached for this workspace" },
          headers: {},
          config: { headers: new AxiosHeaders() },
        },
      ),
    );

    await fillAndSubmit();

    expect(
      await screen.findByText("Could not create the agent"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Agent limit reached for this workspace"),
    ).toBeInTheDocument();

    await waitFor(() => expect(createNl2sqlAgent).toHaveBeenCalledTimes(1));
    expect(testConnection).toHaveBeenCalledTimes(1);
    expect(addDatabase).not.toHaveBeenCalled();
    expect(screen.queryByText(/is ready/)).not.toBeInTheDocument();
  });

  /**
   * The schema is the gate, not a check beside it: submitting with nothing
   * filled names every missing field and calls nothing, and filling one in
   * clears just that one.
   */
  it("names the missing fields from the schema and calls nothing", async () => {
    const user = userEvent.setup();
    renderWizard(<NewAgentWizard onClose={() => {}} />);
    await user.click(
      screen.getByRole("button", { name: "Next — connect a database" }),
    );
    await user.click(
      screen.getByRole("button", { name: "Test & create agent" }),
    );

    expect(
      await screen.findByText(
        "Still needed: Host, Database name, Username, Password",
      ),
    ).toBeInTheDocument();
    expect(testConnection).not.toHaveBeenCalled();
    expect(createNl2sqlAgent).not.toHaveBeenCalled();

    await user.type(screen.getByLabelText(/^Host/), "db.example.com");
    expect(
      await screen.findByText(
        "Still needed: Database name, Username, Password",
      ),
    ).toBeInTheDocument();
  });
});
