"use client";

import { useState } from "react";

import Icon from "@/components/Icon";

import { LOG_DOT, LOG_LABEL } from "./constants";
import { formatCost, formatMs, type RunLog, type RunLogStep } from "./runLog";

/**
 * Everything the run did in the background, folded away under the answer.
 *
 * The trace above an answer is the headline — SQL written, table read, rows
 * returned. This is the transcript: the question as the service rewrote it,
 * the database and tables it picked, the query in full, what running it
 * returned, and what the chart step decided. Every line is a field the service
 * reported; a run that reports less simply logs fewer steps.
 */
export default function FullLogs({ log }: { log: RunLog }) {
  const [open, setOpen] = useState(false);
  const [unfolded, setUnfolded] = useState<Record<string, boolean>>({});

  const summary = [
    ...(log.runType ? [log.runType] : []),
    ...(log.totals?.latencyMs ? [formatMs(log.totals.latencyMs)] : []),
    ...(log.totals?.totalTokens
      ? [`${log.totals.totalTokens.toLocaleString()} tokens`]
      : []),
    ...(log.totals?.costUsd ? [formatCost(log.totals.costUsd)] : []),
  ];

  return (
    <div className="overflow-hidden rounded-xl border border-n2s-line bg-n2s-card">
      <button
        type="button"
        data-demo="full-logs"
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
        className="flex w-full cursor-pointer items-center gap-2.5 border-0 bg-transparent px-3.5 py-2.5 text-left hover:bg-n2s-card-2"
      >
        <Icon
          name="caretRight"
          className={`size-3.5 flex-none text-n2s-ink-3 transition-transform duration-200 ${
            open ? "rotate-90" : ""
          }`}
          strokeWidth={2.4}
        />
        <span className="text-[12.5px] font-bold text-n2s-ink">Full logs</span>
        <span className="truncate text-[11px] text-n2s-ink-3">
          {log.steps.length === 1 ? "1 step" : `${log.steps.length} steps`}
        </span>
        <div className="flex-1" />
        {log.traceId && (
          <span
            className="hidden max-w-[180px] truncate font-mono text-[10.5px] text-n2s-ink-3 sm:inline"
            title={`Trace ${log.traceId}`}
          >
            {log.traceId}
          </span>
        )}
        {log.totals?.latencyMs !== undefined && (
          <span className="whitespace-nowrap font-mono text-[11px] text-n2s-ink-3">
            {formatMs(log.totals.latencyMs)}
          </span>
        )}
      </button>

      {open && (
        <div className="border-t border-n2s-line">
          {/* The run as a whole. Tokens and cost ride a `usage` block the
              service does not send today, so a turn without one says what it
              has rather than printing zeroes. */}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-n2s-line bg-n2s-card-2 px-3.5 py-1.5">
            {summary.length ? (
              summary.map((entry, index) => (
                <span
                  key={entry}
                  className={`text-[11px] ${
                    index === 0
                      ? "font-semibold text-n2s-ink-2"
                      : "text-n2s-ink-3"
                  }`}
                >
                  {entry}
                </span>
              ))
            ) : (
              <span className="text-[11px] text-n2s-ink-3">
                This run reported what it did, but not what it took.
              </span>
            )}
          </div>

          {/* Every id the turn carries. Selectable, not buttons: the one thing
              support asks for is an id, and a reader should be able to take it
              without a clipboard permission or a toast. */}
          {!!log.ids?.length && (
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-n2s-line bg-n2s-card-2 px-3.5 py-1.5">
              {log.ids.map((id) => (
                <span
                  key={id.label}
                  className="font-mono text-[10.5px] text-n2s-ink-3 select-all"
                >
                  {id.label} {id.value}
                </span>
              ))}
            </div>
          )}

          <ol
            className="m-0 flex list-none flex-col gap-0 p-0"
            data-demo="log-steps"
          >
            {log.steps.map((step, index) => (
              <LogStep
                key={step.key}
                step={step}
                index={index + 1}
                open={!!unfolded[step.key]}
                onToggle={() =>
                  setUnfolded((current) => ({
                    ...current,
                    [step.key]: !current[step.key],
                  }))
                }
              />
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}

function LogStep({
  step,
  index,
  open,
  onToggle,
}: {
  step: RunLogStep;
  index: number;
  open: boolean;
  onToggle: () => void;
}) {
  const lines = step.lines ?? [];
  const cost = [
    ...(step.call?.latencyMs !== undefined
      ? [formatMs(step.call.latencyMs)]
      : []),
    ...(step.call?.inputTokens !== undefined &&
    step.call.outputTokens !== undefined
      ? [
          `${step.call.inputTokens.toLocaleString()} in / ${step.call.outputTokens.toLocaleString()} out`,
        ]
      : []),
    ...(step.call?.costUsd !== undefined
      ? [formatCost(step.call.costUsd)]
      : []),
  ];

  // A step with nothing underneath is a line, not a fold — an arrow that opens
  // onto an empty box is worse than no arrow.
  const Row = lines.length ? "button" : "div";

  return (
    <li className="border-b border-n2s-line last:border-b-0">
      <Row
        {...(lines.length
          ? {
              type: "button" as const,
              onClick: onToggle,
              "aria-expanded": open,
            }
          : {})}
        className={`flex w-full items-center gap-2.5 border-0 bg-transparent px-3.5 py-2 text-left ${
          lines.length ? "cursor-pointer hover:bg-n2s-card-2" : ""
        }`}
      >
        <span className="w-4 flex-none font-mono text-[10px] text-n2s-ink-3">
          {index}
        </span>
        <span
          className={`grid size-3.5 flex-none place-items-center rounded-full ${LOG_DOT[step.state]}`}
        >
          <Icon
            name={
              step.state === "failed"
                ? "x"
                : step.state === "skipped"
                  ? "ref"
                  : step.state === "flagged"
                    ? "warn"
                    : "chk"
            }
            className="size-2.5"
            strokeWidth={3.4}
          />
        </span>
        <span className={`flex-none text-[12.5px] ${LOG_LABEL[step.state]}`}>
          {step.label}
        </span>
        {step.detail && (
          <span
            className="truncate font-mono text-[11px] text-n2s-ink-3"
            title={step.detail}
          >
            {step.detail}
          </span>
        )}
        <span className="flex-1" />
        {cost.map((entry) => (
          <span
            key={entry}
            className="flex-none font-mono text-[10.5px] text-n2s-ink-3"
          >
            {entry}
          </span>
        ))}
        {!!lines.length && (
          <Icon
            name="caretRight"
            className={`size-3 flex-none text-n2s-ink-3 transition-transform duration-200 ${
              open ? "rotate-90" : ""
            }`}
            strokeWidth={2.4}
          />
        )}
      </Row>

      {open && !!lines.length && (
        <pre className="m-0 max-h-56 overflow-auto border-t border-n2s-line bg-n2s-card-2 px-3.5 py-2 font-mono text-[11px] leading-relaxed whitespace-pre-wrap text-n2s-ink-2">
          {lines.join("\n")}
        </pre>
      )}
    </li>
  );
}
