import type { ReactNode } from "react";

import { cn } from "@/platform/utils";

/**
 * Monospace block with an optional caption bar — the agent UI's snippet
 * treatment (slate surface, mono type, its own horizontal scroll).
 */
export default function CodeBlock({
  caption,
  action,
  children,
  className,
}: {
  caption?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className="overflow-hidden rounded-lg border border-slate-200">
      {(caption || action) && (
        <div className="flex items-center gap-2 border-b border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-500">
          {caption}
          {action && <span className="ml-auto">{action}</span>}
        </div>
      )}
      <pre
        className={cn(
          "overflow-x-auto bg-slate-50 p-3 font-mono text-xs leading-relaxed text-slate-700",
          className,
        )}
      >
        {children}
      </pre>
    </div>
  );
}
