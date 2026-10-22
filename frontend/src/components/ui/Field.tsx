import type { ReactNode } from "react";

import { cn } from "@/platform/utils";

/**
 * Label, optional hint and control — the agent UI's form row, with the hint line
 * its `Label`/`Input` pair does not carry.
 */
export default function Field({
  label,
  htmlFor,
  hint,
  required,
  children,
  className,
}: {
  label: ReactNode;
  htmlFor?: string;
  hint?: ReactNode;
  required?: boolean;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("space-y-1.5", className)}>
      <label
        htmlFor={htmlFor}
        className="block text-sm font-medium text-slate-700"
      >
        {label}
        {required && <span className="ml-0.5 text-rose-500">*</span>}
      </label>
      {hint && <p className="text-xs leading-relaxed text-slate-500">{hint}</p>}
      {children}
    </div>
  );
}
