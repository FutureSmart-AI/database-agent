import type { ReactNode } from "react";

import Icon, { type IconName } from "@/components/Icon";
import { cn } from "@/platform/utils";

export type BannerTone = "info" | "warn" | "ok" | "error";

/** Tinted callout, in the same tones the agent UI uses for inline notices. */
const toneStyles: Record<BannerTone, { box: string; icon: string }> = {
  info: {
    box: "bg-blue-50 border-blue-200 text-blue-900",
    icon: "text-blue-600",
  },
  warn: {
    box: "bg-amber-50 border-amber-200 text-amber-900",
    icon: "text-amber-600",
  },
  ok: {
    box: "bg-emerald-50 border-emerald-200 text-emerald-900",
    icon: "text-emerald-600",
  },
  error: {
    box: "bg-rose-50 border-rose-200 text-rose-900",
    icon: "text-rose-600",
  },
};

const toneIcons: Record<BannerTone, IconName> = {
  info: "info",
  warn: "warn",
  ok: "chk",
  error: "warn",
};

export default function Banner({
  tone = "info",
  title,
  children,
  icon,
  className,
}: {
  tone?: BannerTone;
  title?: ReactNode;
  children?: ReactNode;
  /** Overrides the tone's default glyph — "bolt" reads better on tips. */
  icon?: "bolt" | "spark";
  className?: string;
}) {
  const styles = toneStyles[tone];
  const glyph: IconName =
    icon === "bolt" || icon === "spark" ? "bolt" : toneIcons[tone];

  return (
    <div
      className={cn(
        "flex gap-2 rounded-lg border p-3 text-sm",
        styles.box,
        className,
      )}
    >
      <Icon
        name={glyph}
        className={cn("mt-0.5 size-4 shrink-0", styles.icon)}
      />
      <div className="min-w-0">
        {title && <div className="font-semibold">{title}</div>}
        {children && <div className="text-[13px] opacity-90">{children}</div>}
      </div>
    </div>
  );
}
