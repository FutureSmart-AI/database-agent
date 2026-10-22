import type { ReactNode } from "react";

import Icon, { type IconName } from "@/components/Icon";

/**
 * The agent UI's empty state: a muted circled glyph over a short headline and a
 * supporting line.
 */
export default function EmptyState({
  icon = "search",
  title,
  note,
  action,
}: {
  icon?: IconName;
  title: ReactNode;
  note?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-20 text-center">
      <span className="mb-3 flex size-12 items-center justify-center rounded-full bg-slate-100">
        <Icon name={icon} className="size-5 text-slate-400" />
      </span>
      <div className="text-sm font-medium text-slate-900">{title}</div>
      {note && <p className="mt-1 max-w-sm text-xs text-slate-500">{note}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
