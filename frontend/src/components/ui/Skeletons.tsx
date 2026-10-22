import { AGENT_CARD_HEIGHT, AGENT_GRID } from "@/lib/constants";
import { Skeleton, SkeletonLine } from "@/platform/components/ui/Skeleton";

import { Card } from "./Card";

/**
 * Loading placeholders for this product, built from the agent UI's own
 * `Skeleton` primitives so a page here fades in the same way a page there does
 * — a shimmering outline of the thing that is coming, rather than a line of
 * text saying it is coming.
 *
 * Each skeleton mirrors the real component's box: same grid track, same card
 * height, same internal rhythm, so nothing jumps when the data lands.
 */

/** One card on Home's agent board — see `AgentCard`. */
function AgentCardSkeleton({ delay = 0 }: { delay?: number }) {
  return (
    <div
      className={`flex flex-col overflow-hidden rounded-2xl border border-slate-200 bg-linear-to-br from-blue-50 to-white/80 shadow-sm ${AGENT_CARD_HEIGHT}`}
      aria-hidden="true"
    >
      <div className="flex grow flex-col items-center overflow-hidden p-5">
        <Skeleton
          className="mb-3 size-14 shrink-0 rounded-2xl!"
          delay={delay}
        />
        <SkeletonLine width="w-36" height="h-5" delay={delay + 60} />
        <div className="mt-3">
          <SkeletonLine width="w-28" height="h-3" delay={delay + 120} />
        </div>
        <div className="mt-4 flex flex-wrap justify-center gap-2">
          <Skeleton className="h-5 w-16 rounded-full!" delay={delay + 180} />
          <Skeleton className="h-5 w-20 rounded-full!" delay={delay + 220} />
          <Skeleton className="h-5 w-14 rounded-full!" delay={delay + 260} />
        </div>
      </div>
      <div className="mt-auto flex h-14 items-center justify-center gap-2 border-t border-slate-100 bg-white/50 px-4">
        <Skeleton className="size-7 rounded-lg!" delay={delay + 300} />
        <Skeleton className="size-7 rounded-lg!" delay={delay + 340} />
        <Skeleton className="size-7 rounded-lg!" delay={delay + 380} />
      </div>
    </div>
  );
}

/**
 * Home's board while the agent list is in flight. `leading` is rendered first —
 * Home passes its real "New database agent" tile, so the one control that needs
 * no data stays usable while the rest of the board loads.
 */
export function AgentGridSkeleton({
  count = 5,
  leading,
}: {
  count?: number;
  leading?: React.ReactNode;
}) {
  return (
    <div className={AGENT_GRID} role="status" aria-busy="true">
      {leading}
      {Array.from({ length: count }).map((_, i) => (
        <AgentCardSkeleton key={i} delay={i * 90} />
      ))}
      <span className="sr-only">Loading your agents</span>
    </div>
  );
}

/** The "Select an agent" picker's cards — see `AgentScope`. */
export function AgentPickerSkeleton({ count = 3 }: { count?: number }) {
  return (
    <div
      className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3"
      role="status"
      aria-busy="true"
    >
      {Array.from({ length: count }).map((_, i) => (
        <Card key={i} className="overflow-hidden">
          <div className="border-b border-slate-100 px-4 py-3 sm:px-6">
            <div className="flex items-center gap-2">
              <Skeleton
                className="size-8 shrink-0 rounded-lg!"
                delay={i * 90}
              />
              <div className="min-w-0 flex-1 space-y-1.5">
                <SkeletonLine width="w-32" height="h-4" delay={i * 90 + 60} />
                <SkeletonLine width="w-24" height="h-3" delay={i * 90 + 120} />
              </div>
              <Skeleton
                className="h-5 w-14 shrink-0 rounded-full!"
                delay={i * 90 + 180}
              />
            </div>
          </div>
          <div className="px-4 py-4 sm:px-6">
            <SkeletonLine width="w-28" height="h-3" delay={i * 90 + 240} />
          </div>
        </Card>
      ))}
      <span className="sr-only">Loading your agents</span>
    </div>
  );
}

/**
 * The rows of a table that has not arrived yet — used inside a `Card` in place
 * of the real `<table>`, so a panel keeps its height while it loads instead of
 * collapsing to a line of text and then jumping.
 */
export function TableSkeleton({
  rows = 5,
  cols = 4,
}: {
  rows?: number;
  cols?: number;
}) {
  return (
    <div className="px-4 py-3 sm:px-6" role="status" aria-busy="true">
      <div
        className="grid gap-4 border-b border-slate-100 pb-3"
        style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}
      >
        {Array.from({ length: cols }).map((_, c) => (
          <SkeletonLine key={c} width="w-20" height="h-3" delay={c * 60} />
        ))}
      </div>
      {Array.from({ length: rows }).map((_, r) => (
        <div
          key={r}
          className="grid gap-4 border-b border-slate-50 py-3 last:border-0"
          style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}
        >
          {Array.from({ length: cols }).map((_, c) => (
            <SkeletonLine
              key={c}
              width={c === 0 ? "w-4/5" : "w-2/3"}
              height="h-3.5"
              delay={r * 80 + c * 40}
            />
          ))}
        </div>
      ))}
      <span className="sr-only">Loading</span>
    </div>
  );
}

/** Stacked rows, for the list panels (conversations). */
export function RowsSkeleton({
  rows = 5,
  className = "",
}: {
  rows?: number;
  className?: string;
}) {
  return (
    <div className={`space-y-3 ${className}`} role="status" aria-busy="true">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center gap-3">
          <Skeleton className="size-8 shrink-0 rounded-lg!" delay={i * 80} />
          <div className="min-w-0 flex-1 space-y-1.5">
            <SkeletonLine width="w-2/5" height="h-3.5" delay={i * 80 + 60} />
            <SkeletonLine width="w-3/5" height="h-3" delay={i * 80 + 120} />
          </div>
        </div>
      ))}
      <span className="sr-only">Loading</span>
    </div>
  );
}
