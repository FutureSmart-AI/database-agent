/**
 * Class strings for the hand-rolled tables in this app, lifted from the agent
 * UI's DataTable so a table here is indistinguishable from one there.
 *
 * DataTable itself is used where a table needs its sorting, pagination and
 * fullscreen behaviour; these constants cover the small, bespoke grids (query
 * result previews, node traces) that only need its look.
 */
export const TABLE = {
  wrap: "overflow-auto [&::-webkit-scrollbar]:h-1.5 [&::-webkit-scrollbar]:w-1.5 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-slate-300 [&::-webkit-scrollbar-track]:bg-transparent",
  table: "w-full",
  headRow: "bg-slate-50 border-b border-slate-200",
  th: "px-4 py-2.5 text-left text-[11px] font-semibold uppercase tracking-wider text-slate-500 whitespace-nowrap",
  thNumeric:
    "px-4 py-2.5 text-right text-[11px] font-semibold uppercase tracking-wider text-slate-500 whitespace-nowrap",
  row: "border-b border-slate-100 last:border-0 hover:bg-slate-50",
  rowActive: "bg-indigo-50/50",
  td: "px-4 py-2.5 text-sm text-slate-700",
  tdNumeric: "px-4 py-2.5 text-right text-sm tabular-nums text-slate-700",
  tdMuted: "px-4 py-2.5 text-sm italic text-slate-400",
  footer:
    "flex items-center gap-2 border-t border-slate-200 bg-slate-50 px-4 py-2 text-xs text-slate-500",
} as const;
