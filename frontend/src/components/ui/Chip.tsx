import type { ReactNode } from "react";

import { cn } from "@/platform/utils";

export type ChipTone =
  "indigo" | "slate" | "green" | "amber" | "blue" | "purple" | "rose";

/**
 * The agent UI's status pill: a tinted fill with an inset ring, as on its agent
 * cards and its NL2SQL service header.
 */
const toneStyles: Record<ChipTone, string> = {
  indigo: "bg-indigo-50 text-indigo-700 ring-indigo-200",
  slate: "bg-slate-50 text-slate-600 ring-slate-200",
  green: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  amber: "bg-amber-50 text-amber-700 ring-amber-200",
  blue: "bg-blue-50 text-blue-700 ring-blue-100",
  purple: "bg-purple-50 text-purple-700 ring-purple-200",
  rose: "bg-rose-50 text-rose-700 ring-rose-200",
};

/**
 * A status pill with room for an icon — the agent UI's `StatusBadge` takes a
 * plain string, and several badges here carry a leading glyph.
 */
export default function Chip({
  children,
  tone = "indigo",
  size = "md",
  className,
  title,
}: {
  children: ReactNode;
  tone?: ChipTone;
  size?: "sm" | "md";
  className?: string;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex items-center gap-1 rounded-full font-medium whitespace-nowrap ring-1 ring-inset",
        size === "sm" ? "px-2 py-0.5 text-[11px]" : "px-2.5 py-1 text-xs",
        toneStyles[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
