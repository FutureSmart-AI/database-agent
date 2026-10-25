"use client";

import { useState, type FormEvent } from "react";

import { useReportAnswer, type ReportCategory } from "@/data/conversations";
import { friendlyApiMessage } from "@/lib/apiError";

const categories: { key: ReportCategory; label: string }[] = [
  { key: "wrong_answer", label: "Wrong numbers or rows" },
  { key: "lost_context", label: "Ignored the earlier question" },
  { key: "wrong_chart", label: "Chart missing or wrong" },
  { key: "error", label: "Error or no answer" },
  { key: "slow", label: "Too slow" },
  { key: "other", label: "Something else" },
];

interface ReportProblemProps {
  agentId: string;
  sessionId: string;
  chatId: string;
}

/**
 * "Report a problem" under an answer.
 *
 * The person says what went wrong and, optionally, what they expected. The
 * service attaches the conversation up to this answer — every question, the
 * SQL, the rows and the chart — so the report can be reproduced without asking
 * them for screenshots. They get a report id to quote.
 */
export default function ReportProblem({
  agentId,
  sessionId,
  chatId,
}: ReportProblemProps) {
  const report = useReportAnswer(agentId);
  const [open, setOpen] = useState(false);
  const [category, setCategory] = useState<ReportCategory>("wrong_answer");
  const [note, setNote] = useState("");
  const [expected, setExpected] = useState("");

  if (report.data) {
    return (
      <span role="status" className="text-n2s-ink-2">
        Reported as{" "}
        <span className="font-mono font-semibold text-n2s-ink">
          {report.data.report_id}
        </span>
        . Thank you.
      </span>
    );
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="cursor-pointer bg-transparent text-n2s-ink-3 underline-offset-2 hover:text-n2s-ink hover:underline"
      >
        Report a problem
      </button>
    );
  }

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!note.trim()) return;
    report.mutate({ sessionId, chatId, category, note, expected });
  };

  return (
    <form
      onSubmit={submit}
      aria-label="Report a problem with this answer"
      className="flex w-full max-w-160 flex-col gap-2.5 rounded-xl border border-n2s-line bg-n2s-card-2 p-3.5 text-[12.5px]"
    >
      <fieldset className="m-0 flex flex-wrap gap-1.5 border-0 p-0">
        <legend className="mb-1.5 p-0 font-semibold text-n2s-ink">
          What went wrong?
        </legend>
        {categories.map((option) => (
          <label
            key={option.key}
            className={`cursor-pointer rounded-full border px-2.5 py-1 ${
              category === option.key
                ? "border-n2s-pri bg-n2s-pri-wash text-n2s-pri-ink"
                : "border-n2s-line bg-n2s-card text-n2s-ink-2"
            }`}
          >
            <input
              type="radio"
              name={`report-${chatId}`}
              value={option.key}
              checked={category === option.key}
              onChange={() => setCategory(option.key)}
              className="sr-only"
            />
            {option.label}
          </label>
        ))}
      </fieldset>
      <label className="flex flex-col gap-1 text-n2s-ink-2">
        Describe the problem
        <textarea
          required
          rows={2}
          maxLength={4000}
          value={note}
          onChange={(event) => setNote(event.target.value)}
          placeholder="e.g. The total for March is lower than the orders table shows."
          className="rounded-lg border border-n2s-line bg-n2s-card px-2.5 py-2 text-n2s-ink"
        />
      </label>
      <label className="flex flex-col gap-1 text-n2s-ink-2">
        What did you expect? (optional)
        <textarea
          rows={2}
          maxLength={4000}
          value={expected}
          onChange={(event) => setExpected(event.target.value)}
          placeholder="The answer, number or chart you expected."
          className="rounded-lg border border-n2s-line bg-n2s-card px-2.5 py-2 text-n2s-ink"
        />
      </label>
      <p className="m-0 text-[11.5px] text-n2s-ink-3">
        Your questions in this conversation, the SQL and the results are
        attached automatically.
      </p>
      {report.error && (
        <p role="alert" className="m-0 text-n2s-err">
          {friendlyApiMessage(report.error, "Could not send the report.")}
        </p>
      )}
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={!note.trim() || report.isPending}
          className="cursor-pointer rounded-lg bg-n2s-pri px-3 py-1.5 text-xs font-semibold text-white hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {report.isPending ? "Sending…" : "Send report"}
        </button>
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="cursor-pointer rounded-lg border border-n2s-line bg-n2s-card px-3 py-1.5 text-xs font-semibold text-n2s-ink-2 hover:text-n2s-ink"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
