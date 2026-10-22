"use client";

import Icon from "@/components/Icon";

import { THINKING_DOTS, TRACE_DOT, TRACE_LABEL } from "./constants";
import type { TraceRow } from "./deriveTrace";

interface RunTraceProps {
  rows: TraceRow[];
}

/**
 * What the run did, as the answer arrives and once it lands.
 *
 * Every row comes from `deriveTrace`, which only reports what the stream
 * evidenced — see the note there on why there are no timed placeholder stages.
 */
export default function RunTrace({ rows }: RunTraceProps) {
  if (!rows.length) return null;

  return (
    <div
      className="overflow-hidden rounded-xl border border-n2s-line bg-n2s-card shadow-n2s-low"
      aria-live="polite"
      data-demo="run-trace"
    >
      <ul className="flex flex-col gap-2.5 px-3.5 py-3">
        {rows.map((row) => (
          <li key={row.key} className="flex items-center gap-2.5 text-[12.5px]">
            {/* A stage still running shows a plain filled dot: a check beside
                "Thinking" reads as a step that already finished. */}
            <span
              className={`grid size-3.5 flex-none place-items-center rounded-full ${TRACE_DOT[row.state]}`}
            >
              {row.state === "active" ? (
                <span className="size-1.5 rounded-full bg-n2s-pri" />
              ) : (
                <Icon
                  name={row.state === "failed" ? "x" : "chk"}
                  className="size-2.5"
                  strokeWidth={3.4}
                />
              )}
            </span>
            <span className={TRACE_LABEL[row.state]}>{row.label}</span>
            {row.state === "active" && (
              <span className="flex items-center gap-[3px]" aria-hidden="true">
                {THINKING_DOTS.map((dot) => (
                  <span
                    key={dot}
                    className={`size-[3px] rounded-full bg-n2s-pri ${dot}`}
                  />
                ))}
              </span>
            )}
            {row.detail && (
              <span
                className="truncate font-mono text-[11.5px] text-n2s-ink-3"
                title={row.detail}
              >
                {row.detail}
              </span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
