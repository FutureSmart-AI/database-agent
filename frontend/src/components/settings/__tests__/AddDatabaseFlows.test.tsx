import type { ReactNode } from "react";

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/platform/components/ToastContext";

import AddDatabaseMenuModal from "../AddDatabaseMenuModal";
import ImportDatabasesModal from "../ImportDatabasesModal";

vi.mock("@/data/databases", () => ({
  addDatabase: vi.fn(),
  generateDescription: vi.fn(),
}));

// `next/font` only loads inside a Next build; the modal shell reads these
// classes at import time.
vi.mock("@/lib/fonts", () => ({ NL2SQL_FONT_CLASS: "font-test" }));

const wrapped = (node: ReactNode) =>
  render(<ToastProvider>{node}</ToastProvider>);

describe("AddDatabaseMenuModal", () => {
  it("offers the three ways in and reports which was picked", async () => {
    const onPick = vi.fn();
    wrapped(<AddDatabaseMenuModal onPick={onPick} onClose={() => {}} />);

    expect(screen.getByText("Manual connection")).toBeTruthy();
    expect(screen.getByText("Import from CSV / JSON")).toBeTruthy();
    expect(screen.getByText("Connect from RDS")).toBeTruthy();

    await userEvent.click(screen.getByText("Connect from RDS"));
    expect(onPick).toHaveBeenCalledWith("rds");
  });
});

describe("ImportDatabasesModal", () => {
  it("keeps Import disabled until rows parse, then reports the count", async () => {
    wrapped(
      <ImportDatabasesModal
        serviceId="NL2SQL_1"
        onClose={() => {}}
        onImported={() => {}}
      />,
    );

    const importButton = screen.getByRole("button", {
      name: "Import databases",
    });
    expect(importButton).toBeDisabled();

    await userEvent.click(screen.getByRole("tab", { name: "Paste JSON" }));
    // Focused directly rather than by click: `paste` goes to whatever has focus,
    // and under a loaded full-suite run the click's focus had not committed yet,
    // so the paste landed nowhere and the box stayed empty.
    screen.getByLabelText("Paste CSV or JSON").focus();
    await userEvent.paste(
      '[{"engine":"postgresql","host":"db1.acme.com","port":5432,"database":"orders","user":"admin","password":"secret"}]',
    );

    // The parse is debounced, so this waits on a timer rather than a render;
    // the default 1s expires under a loaded full-suite run.
    await waitFor(
      () => {
        expect(screen.getByText("1 connection read.")).toBeTruthy();
      },
      { timeout: 4000 },
    );
    expect(
      screen.getByRole("button", { name: "Import databases" }),
    ).not.toBeDisabled();
  });

  it("names the rows it cannot read rather than importing part of the set", async () => {
    wrapped(
      <ImportDatabasesModal
        serviceId="NL2SQL_1"
        onClose={() => {}}
        onImported={() => {}}
      />,
    );

    await userEvent.click(screen.getByRole("tab", { name: "Paste JSON" }));
    // Focused directly rather than by click: `paste` goes to whatever has focus,
    // and under a loaded full-suite run the click's focus had not committed yet,
    // so the paste landed nowhere and the box stayed empty.
    screen.getByLabelText("Paste CSV or JSON").focus();
    await userEvent.paste('[{"engine":"postgresql","host":"db1.acme.com"}]');

    await waitFor(
      () => {
        expect(screen.getByText(/These rows cannot be imported/)).toBeTruthy();
      },
      { timeout: 4000 },
    );
    expect(
      screen.getByRole("button", { name: "Import databases" }),
    ).toBeDisabled();
  });
});
