"use client";

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";

import { cn } from "@/platform/utils";

export interface TabItem<K extends string> {
  key: K;
  label: string;
  /** Trailing count pill, as on the analytics tabs in the agent UI. */
  count?: number;
}

interface IndicatorStyle {
  width?: string;
  transform?: string;
  opacity: number;
}

/**
 * The agent UI's tab strip: pill buttons over a hairline, with an indigo bar
 * that slides to the active tab.
 *
 * Not the shared `Tabs` component itself — that owns its panels, and every view
 * here renders the panel body outside the strip — but the same markup, classes
 * and sliding indicator, so the two look identical.
 */
export default function TabNav<K extends string>({
  tabs,
  activeTab,
  onChange,
  label,
  className,
}: {
  tabs: TabItem<K>[];
  activeTab: K;
  onChange: (key: K) => void;
  label?: string;
  className?: string;
}) {
  const header = useRef<HTMLDivElement>(null);
  const [indicator, setIndicator] = useState<IndicatorStyle>({ opacity: 0 });

  const measure = useCallback(() => {
    const active = header.current?.querySelector<HTMLButtonElement>(
      `[data-tab-key="${activeTab}"]`,
    );
    if (!active) {
      setIndicator({ opacity: 0 });
      return;
    }
    setIndicator({
      width: `${active.offsetWidth}px`,
      transform: `translateX(${active.offsetLeft}px)`,
      opacity: 1,
    });
  }, [activeTab]);

  useLayoutEffect(measure, [measure, tabs]);

  // Wrapping tabs move when the window changes width, so the bar is re-measured
  // rather than left behind under whichever tab used to be there.
  useEffect(() => {
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [measure]);

  return (
    <div
      ref={header}
      role="tablist"
      aria-label={label}
      className={cn(
        "relative flex w-full flex-wrap items-center gap-2 border-b border-slate-200 px-2 pb-1 pt-2 sm:px-4 sm:pt-3",
        className,
      )}
    >
      {tabs.map((tab) => {
        const active = tab.key === activeTab;
        return (
          <button
            key={tab.key}
            role="tab"
            type="button"
            data-tab-key={tab.key}
            aria-selected={active}
            onClick={() => onChange(tab.key)}
            className={cn(
              "group relative inline-flex cursor-pointer items-center gap-2 rounded-full px-4 py-2 text-sm font-medium transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2",
              active
                ? "text-indigo-600"
                : "text-slate-500 hover:text-slate-700",
            )}
          >
            {tab.label}
            {tab.count !== undefined && (
              <span className="rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold text-slate-500">
                {tab.count}
              </span>
            )}
          </button>
        );
      })}
      <span
        aria-hidden="true"
        className="pointer-events-none absolute bottom-0 left-0 h-0.5 rounded-full bg-indigo-500 transition-all duration-300 ease-out"
        style={indicator}
      />
    </div>
  );
}
