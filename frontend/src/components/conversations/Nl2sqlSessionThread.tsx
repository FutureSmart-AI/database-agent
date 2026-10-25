"use client";

import { memo, useCallback, useEffect, useState } from "react";

import { useQuery } from "@tanstack/react-query";

import {
  useChatStream,
  type ChatStreamTransport,
} from "@/platform/hooks/useChatStream";

import Composer from "./Composer";
import Thread from "./Thread";

interface Nl2sqlSessionThreadProps {
  sessionId: string;
  activeTab: string;
  readOnly?: boolean;
  chatTransport?: ChatStreamTransport;
  nl2sqlServiceId?: string | null;
  agentId?: string;
  showSources: boolean;
  showQuery: boolean;
  showResults: boolean;
  rawEnabled: boolean;
  voiceInputEnabled?: boolean;
  voiceOutputEnabled?: boolean;
  /** Tables the agent excludes; passed to the turns for the same gate. */
  excludedTables?: string[];
  /** Starter questions, until the agent suggests its own. */
  initialSuggestedQuestions?: string[];
  /** Shown instead of the composer when no question can be sent. */
  composerBlockedNote?: string | null;
}

/**
 * A stored conversation, opened and replied to.
 *
 * Deliberately mirrors the agent UI's `ConversationData`: a second chat stream
 * scoped to this session, seeded from `fetchSessionDetails` through the same
 * `["itemDetails", sessionId]` cache entry the screen's unanswered-session
 * check subscribes to. Only the rendering differs.
 */
const Nl2sqlSessionThread = ({
  sessionId,
  activeTab,
  readOnly,
  chatTransport,
  nl2sqlServiceId,
  agentId,
  showSources,
  showQuery,
  showResults,
  rawEnabled,
  voiceInputEnabled,
  voiceOutputEnabled,
  excludedTables,
  initialSuggestedQuestions,
  composerBlockedNote,
}: Nl2sqlSessionThreadProps) => {
  const {
    loading,
    fetchSessionDetails,
    callStreamAnswer,
    addMessage,
    resetChat,
    sessionMessages,
    chatId,
    error,
  } = useChatStream(chatTransport);
  const [inputValue, setInputValue] = useState("");
  // Bumped when a suggested follow-up is put into the composer, so Enter sends it.
  const [composerFocus, setComposerFocus] = useState(0);
  const pickQuestion = useCallback((question: string) => {
    setInputValue(question);
    setComposerFocus((n) => n + 1);
  }, []);
  const [messageLoading, setMessageLoading] = useState(false);

  // Clear the thread the moment the selection changes, or the previous
  // conversation's messages show under the new title until the fetch lands.
  useEffect(() => {
    if (sessionId) resetChat();
  }, [sessionId, resetChat]);

  const { isLoading } = useQuery({
    queryKey: ["itemDetails", sessionId],
    queryFn: () => (sessionId ? fetchSessionDetails(sessionId) : null),
    enabled: Boolean(sessionId),
    refetchOnWindowFocus: false,
    refetchOnMount: true,
    staleTime: 0,
    gcTime: 0,
  });

  const handleSendMessage = useCallback(
    async (meta?: { viaVoice?: boolean }) => {
      if (readOnly || !inputValue.trim()) return;
      try {
        addMessage(inputValue, meta?.viaVoice);
        setInputValue("");
        setMessageLoading(true);
        await callStreamAnswer({
          agent_id: agentId,
          session_id: sessionId,
          query: inputValue,
          no_of_chunks: 3,
          use_user_info: false,
          stream: true,
        });
      } finally {
        setMessageLoading(false);
      }
    },
    [addMessage, agentId, callStreamAnswer, inputValue, readOnly, sessionId],
  );

  return (
    <>
      <Thread
        messages={sessionMessages}
        loading={loading || isLoading}
        streaming={messageLoading}
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
        initialSuggestedQuestions={initialSuggestedQuestions}
        onPickQuestion={pickQuestion}
        suggestionsDisabled={Boolean(composerBlockedNote)}
        error={error}
      />
      {readOnly ? (
        <div className="flex-none border-t border-n2s-line bg-n2s-card-2 px-4 py-3 text-center text-[11.5px] text-n2s-ink-3">
          {activeTab === "widget"
            ? "Anonymous widget session — read-only. Replies are not possible here."
            : "Read-only session — switch to My Conversations to send messages."}
        </div>
      ) : (
        <Composer
          value={inputValue}
          onChange={setInputValue}
          onSend={handleSendMessage}
          voiceInputEnabled={voiceInputEnabled}
          blockedNote={composerBlockedNote}
          focusSignal={composerFocus}
        />
      )}
    </>
  );
};

export default memo(Nl2sqlSessionThread);
