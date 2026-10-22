"use client";

import { useMemo } from "react";

import { get } from "lodash-es";

import Icon from "@/components/Icon";
import {
  createSynthesizer,
  toPlainText,
  ttsErrorMessage,
  useTextToSpeech,
} from "@/platform/chat-core/tts";
import ChatFeedbackButtons from "@/platform/components/conversations/ChatFeedbackButtons";
import { CopyToClipboard } from "@/platform/components/conversations/copy-to-clipboard";
import { Markdown } from "@/platform/components/conversations/markdown";
import { normalizeNl2sql } from "@/platform/components/conversations/nl2sql/normalizeNl2sql";
import { ReadAloudButton } from "@/platform/components/conversations/ReadAloudButton";
import { useToast } from "@/platform/components/ToastContext";
import { ttsEnabled, ttsUrl } from "@/platform/config";

import { deriveTrace } from "./deriveTrace";
import FullLogs from "./FullLogs";
import { restrictedTablesInAnswer } from "./restrictedTables";
import ResultCard from "./ResultCard";
import { readRunLog } from "./runLog";
import RunTrace from "./RunTrace";
import { stripResultTables } from "./stripResultTables";

interface TurnBlockProps {
  /** The assistant message for this turn. */
  message: Record<string, unknown>;
  /** The question this answer replies to, for the feedback payload. */
  question: string;
  /** Whether the question was dictated, for the "via voice input" tag. */
  questionViaVoice?: boolean;
  sessionId: string;
  chatId: string;
  activeTab: string;
  readOnly?: boolean;
  nl2sqlServiceId?: string | null;
  /** Whether the agent allows the SQL and rows to be shown at all. */
  showSources: boolean;
  /** Whether the generated query may be shown. */
  showQuery: boolean;
  /** Whether the returned rows may be shown. */
  showResults: boolean;
  /** Whether the agent exposes the untouched API payload. */
  rawEnabled: boolean;
  /** Whether an answer may be read aloud. */
  voiceOutputEnabled?: boolean;
  /**
   * Tables the agent is configured to exclude, by name.
   *
   * An answer that read one of them has its query and its rows withheld here,
   * whatever the run chose to return — see `restrictedTables`.
   */
  excludedTables?: string[];
  /** True while this answer is the one still streaming. */
  streaming: boolean;
  /** Sanitised failure text, when the run reported one. */
  error?: string | null;
}

const answerText = (message: Record<string, unknown>): string =>
  String(get(message, "response") ?? get(message, "message") ?? "");

/** One question and the answer under it, in the artifact's layout. */
export default function TurnBlock({
  message,
  question,
  questionViaVoice,
  sessionId,
  chatId,
  activeTab,
  readOnly,
  nl2sqlServiceId,
  showSources,
  showQuery,
  showResults,
  rawEnabled,
  voiceOutputEnabled,
  excludedTables,
  streaming,
  error,
}: TurnBlockProps) {
  const { toast } = useToast();
  const answer = answerText(message);
  // "Thinking..." is the placeholder the stream seeds an assistant turn with,
  // not an answer — showing it would put the word in the reader's bubble.
  const body = answer === "Thinking..." ? "" : answer;
  const view = showSources ? normalizeNl2sql(message) : null;
  const trace = deriveTrace({
    loading: streaming,
    answer: body,
    view,
    error,
    showQuery,
  });
  /**
   * Tables this answer read that the agent is configured to exclude.
   *
   * Their query and their rows are not drawn — see `restrictedTables`. The
   * trace stays: which table was read is the fact worth reporting, and it is
   * what tells an owner their exclusion is not being honoured.
   */
  const restricted = restrictedTablesInAnswer(view?.tablesUsed, excludedTables);
  /**
   * What the run did in the background. Read once the run has finished: a log
   * of a half-finished run would grow steps under the reader as it went, and
   * the live stages are the trace's job.
   */
  const runLog = streaming
    ? null
    : readRunLog({ message, view, error, showQuery, showResults });
  // The card draws the rows; the answer's own markdown table would repeat them.
  // Only a table that restates the card is dropped — a pivot or a summary the
  // answer wrote over those rows is the answer, and stays. See
  // `stripResultTables`.
  const showsCard =
    showResults &&
    !restricted.length &&
    Boolean(view?.previewRows?.length || view?.chart);
  const prose = showsCard
    ? stripResultTables(body, {
        // `columns` is what the service declared; a result that declared none
        // still has its column names on the row objects.
        columns: view?.columns?.length
          ? view.columns.map((column) => column.name)
          : Object.keys(view?.previewRows?.[0] ?? {}),
        rows: view?.previewRows ?? [],
      })
    : body;

  const synthesize = useMemo(
    () => createSynthesizer({ baseUrl: ttsUrl, withCredentials: true }),
    [],
  );
  const tts = useTextToSpeech({
    synthesize,
    onError: (issue) => toast.error(ttsErrorMessage(issue.kind)),
  });
  const spoken = useMemo(() => toPlainText(body), [body]);

  return (
    <div className="flex flex-col gap-5">
      {question && (
        <div className="flex flex-col items-end gap-1">
          {/* The reader's mark sits beside their question the way the agent's
              sits beside its answer, so a long thread reads as two voices
              rather than as one column of bubbles. */}
          <div className="flex w-full items-start justify-end gap-3">
            <div className="max-w-[70%] rounded-[14px] rounded-br-[4px] bg-n2s-pri px-4 py-2.5 text-[13.5px] leading-relaxed text-white">
              {question}
            </div>
            <span
              className="grid size-7 flex-none place-items-center rounded-[9px] bg-n2s-card-3 text-n2s-ink-2"
              data-testid="asker-avatar"
              data-demo="asker-avatar"
            >
              <Icon name="user" className="size-4" />
            </span>
          </div>
          {questionViaVoice && (
            <span className="mr-10 flex items-center gap-1 text-[10px] text-n2s-ink-3">
              <Icon name="mic" className="size-2.5" />
              via voice input
            </span>
          )}
        </div>
      )}

      <div className="flex gap-3">
        <span className="grid size-7 flex-none place-items-center rounded-[9px] bg-n2s-pri-wash text-n2s-pri">
          <Icon name="bot" className="size-4" />
        </span>
        <div className="flex min-w-0 flex-1 flex-col gap-3.5">
          <RunTrace rows={trace} />

          {prose && (
            <div className="text-[13.5px] leading-relaxed text-n2s-ink-2">
              <Markdown>{prose}</Markdown>
            </div>
          )}

          {restricted.length > 0 && (
            <p
              className="m-0 rounded-xl border border-n2s-amber/25 bg-n2s-amber-wash px-4 py-3 text-[12.5px] text-n2s-ink-2"
              role="status"
            >
              This answer read{" "}
              <span className="font-semibold">{restricted.join(", ")}</span>,
              which this agent is set to exclude, so its query and rows are not
              shown here. Check Tables &amp; visibility under Settings →
              Databases.
            </p>
          )}

          {/* The chart, the rows, the query and the payload are four readings
              of one run, so they share one card and one bar of chrome. A table
              the agent excludes withholds all four — see `restrictedTables`. */}
          {view && !restricted.length && (
            <ResultCard
              view={view}
              raw={message}
              showQuery={showQuery}
              showResults={showResults}
              rawEnabled={rawEnabled}
            />
          )}

          {runLog && <FullLogs log={runLog} />}

          {!streaming && body && (
            <div className="flex items-center gap-3 text-[11.5px]">
              <ChatFeedbackButtons
                sessionId={sessionId}
                chatId={String(get(message, "chat_id") ?? chatId)}
                userFeedback={
                  (get(message, "user_feedback") as string | null) ?? null
                }
                activeTab={activeTab}
                readOnly={readOnly}
                nl2sqlServiceId={nl2sqlServiceId}
                userQuery={question}
                generatedQuery={view?.sqlQuery ?? ""}
              />
              <CopyToClipboard className="w-fit text-n2s-ink-3 hover:text-n2s-ink hover:no-underline">
                {body}
              </CopyToClipboard>
              {voiceOutputEnabled && ttsEnabled && (
                <ReadAloudButton
                  status={tts.status}
                  disabled={!spoken}
                  onPlay={() => tts.play(spoken)}
                  onPause={tts.pause}
                  onResume={tts.resume}
                />
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
