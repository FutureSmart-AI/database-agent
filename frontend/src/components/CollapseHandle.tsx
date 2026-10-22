"use client";

import { cn } from "@/platform/utils";

import Icon from "./Icon";

/**
 * The round chevron that sits on a panel's edge and folds it away.
 *
 * The app shell's own sidebar handle, drawn in this product's tokens: same
 * size, same offset from the top, same half-overlap of the border it rides. It
 * floats on the edge rather than sitting inside the panel, because once a panel
 * is collapsed to a strip there is no room inside it for the control that
 * brings it back — and a second control somewhere else is how a person learns
 * that closing and opening a panel are two different gestures.
 *
 * Document Intelligence carries the same handle, so the conversation rail folds
 * away the same way in both products.
 *
 * The panel it belongs to must be `relative` and must not clip overflow.
 */
export default function CollapseHandle({
  collapsed,
  onToggle,
  label,
  className,
}: {
  collapsed: boolean;
  onToggle: () => void;
  /** Names the action, e.g. "Collapse conversations". */
  label: string;
  className?: string;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-label={label}
      aria-expanded={!collapsed}
      title={collapsed ? "Expand" : "Collapse"}
      className={cn(
        "absolute top-20 -right-3 z-20 flex size-6 cursor-pointer items-center justify-center",
        "rounded-full border border-n2s-line bg-n2s-card text-n2s-ink-2 shadow-n2s-mid",
        "hover:bg-n2s-card-3 hover:text-n2s-ink",
        className,
      )}
    >
      <Icon
        name="caretLeft"
        className={cn(
          "size-4 transition-transform duration-200",
          collapsed && "rotate-180",
        )}
      />
    </button>
  );
}
