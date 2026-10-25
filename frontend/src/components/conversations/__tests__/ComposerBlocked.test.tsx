import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import Composer from "../Composer";

vi.mock("@/platform/components/conversations/MessageBox", () => ({
  default: () => <textarea aria-label="Message" />,
}));

/**
 * A used-up free allowance is said before typing, not after a refused run: the
 * input gives way to the reason, and nothing can be sent.
 */
describe("Composer — no question can be sent", () => {
  it("shows the input normally", () => {
    render(<Composer value="" onChange={vi.fn()} onSend={vi.fn()} />);
    expect(screen.getByLabelText("Message")).toBeTruthy();
  });

  it("replaces the input with the reason when blocked", () => {
    render(
      <Composer
        value=""
        onChange={vi.fn()}
        onSend={vi.fn()}
        blockedNote="No free sample-data questions left."
      />,
    );
    expect(screen.queryByLabelText("Message")).toBeNull();
    expect(screen.getByRole("status").textContent).toBe(
      "No free sample-data questions left.",
    );
  });
});
