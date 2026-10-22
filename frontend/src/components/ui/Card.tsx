import type { ReactNode } from "react";

import { cn } from "@/platform/utils";

/**
 * The agent UI's section panel — `rounded-xl border border-black/5 bg-white
 * shadow-sm`, as used by every panelled page there (Share, Team Access, API
 * keys). Header, body and footer are separate pieces so a card can skip any of
 * them.
 */
export function Card({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "rounded-xl border border-black/5 bg-white shadow-sm",
        className,
      )}
    >
      {children}
    </div>
  );
}

export function CardHeader({
  title,
  note,
  action,
  className,
}: {
  title: ReactNode;
  /** Supporting line, under the title as in the agent UI's panel headers. */
  note?: ReactNode;
  /** Right-aligned controls. */
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn("border-b border-slate-100 px-4 py-3 sm:px-6", className)}
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <h3 className="text-base font-semibold text-slate-900">{title}</h3>
        {action && (
          <div className="ml-auto flex items-center gap-2">{action}</div>
        )}
      </div>
      {note && <p className="mt-1 text-sm text-slate-500">{note}</p>}
    </div>
  );
}

export function CardBody({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return <div className={cn("px-4 py-4 sm:px-6", className)}>{children}</div>;
}

export function CardFooter({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex items-center gap-2 border-t border-slate-100 px-4 py-3 sm:px-6",
        className,
      )}
    >
      {children}
    </div>
  );
}
