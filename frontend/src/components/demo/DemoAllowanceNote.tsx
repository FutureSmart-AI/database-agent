"use client";

import Link from "next/link";

import Icon from "@/components/Icon";
import { demoBlocked, SELF_HOST_URL, type DemoAllowance } from "@/data/demo";
import { ROUTES } from "@/lib/routes";

interface DemoAllowanceNoteProps {
  allowance?: DemoAllowance;
  /** `bar` sits under the chat header; `inline` sits inside the home card. */
  variant: "bar" | "inline";
}

/**
 * How many free sample-data questions are left, and — once they are not — the
 * three ways to keep going: your own key, your own database, or your own copy.
 */
export default function DemoAllowanceNote({
  allowance,
  variant,
}: DemoAllowanceNoteProps) {
  const blocked = demoBlocked(allowance);

  if (blocked) {
    return (
      <div
        role="status"
        className={`border-n2s-amber/25 bg-n2s-amber-wash ${
          variant === "bar"
            ? "flex-none border-b px-6 py-3"
            : "rounded-xl border px-4 py-3"
        }`}
      >
        <p className="m-0 text-sm font-semibold text-n2s-amber">{blocked}</p>
        <p className="m-0 mt-0.5 text-sm text-n2s-ink-2">
          Keep going with your own OpenAI key and your own database, or run
          Database Agent yourself.
        </p>
        <div className="mt-2 flex flex-wrap gap-2">
          <Link
            href={ROUTES.credentials}
            className="inline-flex items-center gap-1.5 rounded-lg bg-n2s-pri px-3 py-1.5 text-xs font-semibold text-white hover:opacity-90"
          >
            <Icon name="key" className="size-3.5" />
            Add your OpenAI key
          </Link>
          <Link
            href={ROUTES.home}
            className="inline-flex items-center gap-1.5 rounded-lg border border-n2s-line bg-n2s-card px-3 py-1.5 text-xs font-semibold text-n2s-ink-2 hover:text-n2s-ink"
          >
            <Icon name="db" className="size-3.5" />
            Connect your database
          </Link>
          <a
            href={SELF_HOST_URL}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 rounded-lg border border-n2s-line bg-n2s-card px-3 py-1.5 text-xs font-semibold text-n2s-ink-2 hover:text-n2s-ink"
          >
            <Icon name="ext" className="size-3.5" />
            Self-host from GitHub
          </a>
        </div>
      </div>
    );
  }

  const counts = !allowance
    ? null
    : allowance.unlimited
      ? "Unlimited questions for FutureSmart team accounts"
      : `${allowance.daily_remaining} of ${allowance.daily_limit} free questions left today · ${allowance.total_remaining} of ${allowance.total_limit} in total`;

  if (variant === "inline") {
    return counts ? (
      <p className="m-0 text-xs font-medium text-n2s-ink-3">{counts}</p>
    ) : null;
  }

  return (
    <div className="flex flex-none flex-wrap items-center gap-x-3 gap-y-1 border-b border-n2s-line bg-n2s-pri-wash px-6 py-2 text-xs text-n2s-ink-2">
      <span className="inline-flex items-center gap-1.5 font-semibold text-n2s-pri-ink">
        <Icon name="spark" className="size-3.5" />
        Sample data · read-only
      </span>
      <span>
        Made-up data, free to explore — no key or database needed.
        {counts ? ` ${counts}.` : ""}
      </span>
    </div>
  );
}
