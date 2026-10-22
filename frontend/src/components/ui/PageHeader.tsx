import type { ReactNode } from "react";

/**
 * The agent UI's page heading: the brand gradient over a muted supporting line,
 * with the page's primary action on the right.
 */
export default function PageHeader({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <h1 className="bg-linear-to-r from-slate-900 via-indigo-700 to-blue-600 bg-clip-text text-2xl font-bold tracking-tight text-transparent">
          {title}
        </h1>
        {subtitle && (
          <p className="mt-1 max-w-3xl text-sm text-slate-600">{subtitle}</p>
        )}
      </div>
      {action && <div className="flex items-center gap-2">{action}</div>}
    </div>
  );
}
