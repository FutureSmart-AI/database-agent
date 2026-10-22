"use client";

import { type ReactNode } from "react";

import { NL2SQL_FONT_CLASS } from "@/lib/fonts";
import { Modal as AgentModal } from "@/platform/components/ui";

interface ModalProps {
  title: string;
  /** Supporting line under the title. */
  sub?: ReactNode;
  /** Wide variant, for the multi-step flows. */
  wide?: boolean;
  /** Rendered between the header and the body — the wizard's step rail. */
  rail?: ReactNode;
  footer: ReactNode;
  children: ReactNode;
  onClose: () => void;
}

/**
 * The agent UI's Modal with the one extra slot this app's flows need: a step
 * rail above the body.
 *
 * The panel, scrim, focus trap, Escape handling and the supporting line under
 * the title all come from the shared component, so a dialog here is the same
 * object as a dialog in the agent UI — same rounding, same slate footer, same
 * animation.
 */
export default function Modal({
  title,
  sub,
  wide,
  rail,
  footer,
  children,
  onClose,
}: ModalProps) {
  return (
    <AgentModal
      open
      // Composed rather than passed as `description`, which only takes a string
      // — some of these supporting lines carry markup. Same classes either way.
      // The shared Modal portals its panel to `document.body`, which is outside
      // the shell's subtree — so each slot re-enters the product's scope. It is
      // `n2s-scope` rather than `n2s-root`: the panel keeps its own white
      // surface, and only the tokens, palette and type come across.
      title={
        <div className={`n2s-scope ${NL2SQL_FONT_CLASS}`}>
          <h2 className="text-lg font-semibold leading-snug text-slate-900">
            {title}
          </h2>
          {sub && <p className="mt-1 text-sm text-slate-500">{sub}</p>}
        </div>
      }
      maxWidth={wide ? "4xl" : "2xl"}
      onCancel={onClose}
      // The shared Modal only lays out its own default footer; a custom one has
      // to align itself, and these actions belong on the right as they do there.
      footer={
        <div
          className={`n2s-scope flex items-center justify-end gap-2.5 ${NL2SQL_FONT_CLASS}`}
        >
          {footer}
        </div>
      }
    >
      <div className={`n2s-scope ${NL2SQL_FONT_CLASS}`}>
        {rail && <div className="mb-4">{rail}</div>}
        {children}
      </div>
    </AgentModal>
  );
}
