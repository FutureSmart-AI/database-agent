"use client";

import { useEffect, useRef } from "react";

import Icon from "@/components/Icon";
import { useFollowUpQuestions } from "@/platform/hooks/useFollowUpQuestions";

import FollowUps from "./FollowUps";
import { toTurns } from "./toTurns";
import TurnBlock from "./TurnBlock";

interface ThreadProps {
  messages: unknown[];
  loading: boolean;
  /** True while the newest answer is still streaming. */
  streaming: boolean;
  sessionId: string;
  chatId: string;
  activeTab: string;
  readOnly?: boolean;
  nl2sqlServiceId?: string | null;
  showSources: boolean;
  showQuery: boolean;
  showResults: boolean;
  rawEnabled: boolean;
  voiceOutputEnabled?: boolean;
  /** Tables the agent excludes; an answer that read one withholds its query. */
  excludedTables?: string[];
  /** Starter questions, shown until the agent suggests its own. */
  initialSuggestedQuestions?: string[];
  /** Puts a suggested question into the composer. */
  onPickQuestion: (question: string) => void;
  /** No question can be sent right now: follow-up suggestions are not offered. */
  suggestionsDisabled?: boolean;
  error?: string | null;
}

export default function Thread({
  messages,
  loading,
  streaming,
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
  initialSuggestedQuestions,
  onPickQuestion,
  suggestionsDisabled = false,
  error,
}: ThreadProps) {
  const scroller = useRef<HTMLDivElement>(null);
  const turns = toTurns(messages);
  const followUps = useFollowUpQuestions({
    sessionMessages: messages,
    initialSuggestedQuestions,
  });

  // Follow the thread only when the reader is already at the bottom, so
  // scrolling back through an answer is not yanked away by the next chunk.
  useEffect(() => {
    const element = scroller.current;
    if (!element) return;
    const distance =
      element.scrollHeight - element.scrollTop - element.clientHeight;
    if (distance < 160) element.scrollTop = element.scrollHeight;
  }, [messages, streaming]);

  if (loading) {
    return (
      <div className="flex flex-1 items-center justify-center gap-2 text-sm text-n2s-ink-3">
        <Icon name="spinner" className="size-4 animate-spin" />
        Loading this conversation…
      </div>
    );
  }

  return (
    <div
      ref={scroller}
      className="min-h-0 flex-1 overflow-y-auto px-6 pt-6 pb-2"
    >
      <div className="mx-auto flex max-w-205 flex-col gap-5">
        {error && (
          <div className="rounded-xl border border-n2s-err/25 bg-n2s-err-wash px-4 py-3 text-[12.5px] text-n2s-err">
            {error}
          </div>
        )}

        {!turns.length && !error && (
          <p className="py-8 text-center text-sm text-n2s-ink-3">
            No messages in this conversation yet.
          </p>
        )}

        {turns.map((turn, index) => {
          const last = index === turns.length - 1;
          return turn.answer ? (
            <TurnBlock
              key={turn.key}
              message={turn.answer}
              question={turn.question}
              sessionId={sessionId}
              chatId={chatId}
              activeTab={activeTab}
              readOnly={readOnly}
              nl2sqlServiceId={nl2sqlServiceId}
              showSources={showSources}
              showQuery={showQuery}
              showResults={showResults}
              rawEnabled={rawEnabled}
              voiceOutputEnabled={voiceOutputEnabled}
              excludedTables={excludedTables}
              questionViaVoice={turn.questionViaVoice}
              streaming={last && streaming}
              error={last ? error : null}
            />
          ) : (
            // A question whose answer has not started arriving yet.
            <TurnBlock
              key={turn.key}
              message={{ role: "assistant", response: "" }}
              question={turn.question}
              sessionId={sessionId}
              chatId={chatId}
              activeTab={activeTab}
              readOnly={readOnly}
              nl2sqlServiceId={nl2sqlServiceId}
              showSources={showSources}
              showQuery={showQuery}
              showResults={showResults}
              rawEnabled={rawEnabled}
              voiceOutputEnabled={voiceOutputEnabled}
              excludedTables={excludedTables}
              questionViaVoice={turn.questionViaVoice}
              streaming
            />
          );
        })}

        {!streaming && turns.length > 0 && (
          <FollowUps
            questions={followUps}
            onPick={onPickQuestion}
            disabled={suggestionsDisabled}
          />
        )}
      </div>
    </div>
  );
}
