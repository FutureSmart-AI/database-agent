"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

import Icon, { type IconName } from "@/components/Icon";
import { cn } from "@/platform/utils";

import { ROW_CLOSE_MS, ROW_EASE, ROW_OPEN_MS } from "./constants";

const reduceMotion = () =>
  typeof window !== "undefined" &&
  Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)").matches);

/**
 * One share feature, collapsed to a single row.
 *
 * Every way out of this product used to be a card standing permanently open,
 * which put the API, the people list and the appearance editor below the fold —
 * you only found out you could invite someone by scrolling. So each feature is
 * a row carrying its name, a one-line purpose and its primary control, with
 * everything else behind the disclosure.
 *
 * Two things are structural rather than incidental:
 *
 * `control` is rendered as a SIBLING of the header button, never inside it. A
 * switch nested in a button is both a nested interactive element and a row that
 * expands whenever you toggle the channel — the click cannot reach the header
 * from here, so that is impossible by construction rather than by a
 * `stopPropagation` somebody can delete later.
 *
 * The body is a padding-free clipper wrapping a padded panel, so its height
 * animates from 0 with nothing jumping, and no inline height survives the
 * animation: both are cancelled on finish, which hands height back to `auto` so
 * a body that grows later (a key issued, a domain added) is not clipped to the
 * height it had when it opened.
 */
export default function ShareRow({
  id,
  icon,
  title,
  purpose,
  control,
  accent = false,
  open,
  onToggle,
  children,
}: {
  /** Used for `aria-controls`; must be unique on the page. */
  id: string;
  icon: IconName;
  title: string;
  /** The one line that says what this is while the row is closed. */
  purpose: ReactNode;
  /** Primary control, kept reachable without opening the row. */
  control?: ReactNode;
  /** Left spine — set on the three channels people actually reach you through. */
  accent?: boolean;
  open: boolean;
  onToggle: (open: boolean) => void;
  children: ReactNode;
}) {
  /**
   * The body is mounted while open, and kept mounted through the closing
   * animation so there is something left to animate. Collapsed rows render
   * nothing, which is what keeps the preview and the key list from fetching for
   * a row nobody has opened.
   */
  const [mounted, setMounted] = useState(open);
  const clipRef = useRef<HTMLDivElement>(null);
  const innerRef = useRef<HTMLDivElement>(null);
  const first = useRef(true);
  /**
   * The height animation currently running on the clipper, if any.
   *
   * A row toggled mid-animation must carry on from the height it is actually at:
   * the one still running is measured BEFORE it is cancelled, because cancelling
   * drops the effect and the clipper snaps back to its resting height — measure
   * after, and a row closed halfway through opening jumps to full height for a
   * frame before it collapses.
   */
  const running = useRef<Animation | null>(null);

  /** Measures the clipper as it stands, then clears whatever was animating it. */
  const takeOver = (clip: HTMLDivElement | null) => {
    const animation = running.current;
    const height =
      animation && clip ? clip.getBoundingClientRect().height : null;
    animation?.cancel();
    running.current = null;
    return height;
  };

  // Nothing outlives the row itself.
  useEffect(
    () => () => {
      running.current?.cancel();
      running.current = null;
    },
    [],
  );

  useEffect(() => {
    if (open) {
      setMounted(true);
      return;
    }
    const clip = clipRef.current;
    if (first.current || !clip || reduceMotion() || !clip.animate) {
      takeOver(clip);
      setMounted(false);
      return;
    }
    const from = takeOver(clip) ?? clip.getBoundingClientRect().height;
    const closing = clip.animate([{ height: `${from}px` }, { height: "0px" }], {
      duration: ROW_CLOSE_MS,
      easing: ROW_EASE,
      fill: "both",
    });
    running.current = closing;
    closing.onfinish = () => {
      if (running.current !== closing) return;
      running.current = null;
      closing.cancel();
      setMounted(false);
    };
  }, [open]);

  useEffect(() => {
    const clip = clipRef.current;
    const inner = innerRef.current;
    // `first` keeps a row that starts open from animating on first paint.
    if (first.current) {
      first.current = false;
      return;
    }
    if (!open || !mounted || !clip || !inner || reduceMotion() || !clip.animate)
      return;
    // A fresh open starts at nothing; one that interrupts a close picks the
    // height up where that close left it.
    const from = takeOver(clip) ?? 0;
    const to = inner.getBoundingClientRect().height;
    const opening = clip.animate(
      [{ height: `${from}px` }, { height: `${to}px` }],
      { duration: ROW_OPEN_MS, easing: ROW_EASE, fill: "both" },
    );
    running.current = opening;
    // The panel travels the last few pixels itself, so an opening row reads as
    // content arriving rather than a box growing. Only on a fresh open: content
    // already on screen should not fade in again.
    if (!from)
      inner.animate?.(
        [
          { opacity: 0, transform: "translateY(-6px)" },
          { opacity: 1, transform: "none" },
        ],
        { duration: 240, delay: 40, easing: ROW_EASE, fill: "backwards" },
      );
    opening.onfinish = () => {
      if (running.current !== opening) return;
      running.current = null;
      opening.cancel();
    };
  }, [open, mounted]);

  return (
    <section
      className={cn(
        "overflow-hidden rounded-xl bg-white shadow-sm transition-[border-color,box-shadow] duration-200",
        "border",
        open
          ? "border-indigo-200 shadow-md"
          : "border-black/5 hover:border-indigo-100",
        accent && "border-l-[3px] border-l-indigo-600",
      )}
    >
      <div
        className={cn(
          "flex flex-wrap items-center justify-end gap-x-3 gap-y-1 pr-3 transition-colors duration-200",
          open && "border-b border-slate-100 bg-indigo-50/50",
        )}
      >
        <button
          type="button"
          aria-expanded={open}
          aria-controls={id}
          onClick={() => onToggle(!open)}
          className="group flex min-w-0 flex-1 basis-52 cursor-pointer items-center gap-3 rounded-xl py-2.5 pl-3 text-left focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-indigo-600"
        >
          <Icon
            name="caretRight"
            strokeWidth={2.4}
            className={cn(
              "size-3 shrink-0 transition-[transform,color] duration-200",
              open ? "rotate-90 text-indigo-600" : "text-slate-400",
            )}
          />
          <span
            className={cn(
              "grid size-8 shrink-0 place-items-center rounded-[9px] transition-colors duration-200",
              open ? "bg-indigo-100" : "bg-indigo-50",
            )}
          >
            <Icon name={icon} className="size-4 text-indigo-600" />
          </span>
          <span className="flex min-w-0 flex-col gap-0.5">
            <span className="truncate text-sm font-semibold text-slate-900 group-hover:text-indigo-700">
              {title}
            </span>
            <span className="line-clamp-2 text-[11.5px] leading-snug text-slate-500">
              {purpose}
            </span>
          </span>
        </button>
        {control && (
          <div className="flex shrink-0 flex-wrap items-center justify-end gap-2 py-1.5">
            {control}
          </div>
        )}
      </div>
      <div
        ref={clipRef}
        id={id}
        role="region"
        aria-label={title}
        hidden={!mounted}
        className="overflow-hidden"
      >
        {mounted && (
          <div ref={innerRef} className="space-y-4 px-4 py-4 sm:px-6">
            {children}
          </div>
        )}
      </div>
    </section>
  );
}

/**
 * A numbered band of rows — what this group of features is for, stated once
 * above them. The numbers are the order the screen is actually worked through
 * (pick the ways out, then who gets in, then how it looks), not decoration.
 */
export function ShareGroup({
  step,
  title,
  purpose,
  children,
}: {
  step: number;
  title: string;
  purpose: string;
  children: ReactNode;
}) {
  const headingId = `share-group-${step}`;
  return (
    <section aria-labelledby={headingId} className="space-y-3.5">
      <div className="flex items-start gap-2.5 px-0.5">
        <span className="mt-0.5 grid size-[22px] shrink-0 place-items-center rounded-full bg-indigo-50 text-[12px] font-bold text-indigo-700">
          {step}
        </span>
        <div>
          <h2
            id={headingId}
            className="text-xs font-bold tracking-[0.06em] text-slate-900 uppercase"
          >
            {title}
          </h2>
          <p className="mt-0.5 text-sm text-slate-500">{purpose}</p>
        </div>
      </div>
      <div className="space-y-3.5">{children}</div>
    </section>
  );
}
