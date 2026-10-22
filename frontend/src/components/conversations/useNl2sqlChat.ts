"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";

import { useQuery, useQueryClient } from "@tanstack/react-query";

import {
  deleteNl2sqlSession,
  fetchNl2sqlSessions,
  nl2sqlChatTransport,
  renameNl2sqlSession,
} from "@/data/nl2sqlChat";
import {
  readOpenedSessions,
  writeOpenedSessions,
  type OpenedSession,
} from "@/data/openedSessions";
import {
  isReadOnlyTab,
  type ConversationTab,
} from "@/platform/components/conversations/constants";
import { useAuth } from "@/platform/hooks/useAuth";
import { useChatStream } from "@/platform/hooks/useChatStream";
import type { ConversationSession } from "@/platform/types/session";
import axios from "@/platform/utils/axios";

/**
 * Stable empty list: `useFollowUpQuestions` re-seeds on identity, so a fresh
 * `[]` every render would re-set its state on every render.
 */
const EMPTY_QUESTIONS: string[] = [];

/**
 * Everything the NL2SQL conversations screen needs that is not presentation.
 *
 * The exclusive session source, the locally-held session ids that cover the
 * service's empty list, the transport, the agent configuration and the
 * unanswered-session check all live here, so that whatever renders the screen
 * shares one implementation of them.
 */
export function useNl2sqlChat() {
  const { agentId, nl2sqlId } = useAuth();
  const queryClient = useQueryClient();

  const [selectedConversations, setSelectedConversations] = useState<
    Record<ConversationTab, string | null>
  >({ dashboard: null, userHistory: null, widget: null });
  const [activeTab, setActiveTab] = useState<ConversationTab>("dashboard");
  const [selectedSessionMeta, setSelectedSessionMeta] =
    useState<ConversationSession | null>(null);
  const [isNewChatViewActive, setIsNewChatViewActive] = useState(true);
  const [inputValue, setInputValue] = useState("");
  const [messageLoading, setMessageLoading] = useState(false);

  const readOnly = isReadOnlyTab(activeTab);
  const selectedItemData = selectedConversations[activeTab];
  const previousSessionIdRef = useRef<string>("");

  // Questions go to the NL2SQL service, not to the chat service: this product is
  // the standalone NL2SQL experience, so the service that owns the databases
  // owns the asking, the session it opens and the thread that is read back.
  const chatTransport = useMemo(
    () => nl2sqlChatTransport(nl2sqlId),
    [nl2sqlId],
  );

  /**
   * Sessions this browser opened, kept until the service lists them.
   *
   * `GET …/{service_id}/sessions` answers `{"sessions": []}` today even for an
   * agent that has just been asked something (the session itself is readable by
   * id), so a thread that was answered a moment ago is in no list at all — and
   * the conversation list, finding the selected id missing, moved the selection
   * to some older conversation. Holding the ids opened here keeps the thread
   * that was just answered selected and listed; each is dropped the moment the
   * service returns it, so this disappears on its own once the list is fixed.
   *
   * Seeded after mount rather than during render: this app is a static export,
   * so reading `localStorage` while rendering would not match the prerendered
   * HTML.
   */
  const [openedSessions, setOpenedSessions] = useState<OpenedSession[]>([]);
  useEffect(() => {
    setOpenedSessions(readOpenedSessions(nl2sqlId));
  }, [nl2sqlId]);

  /**
   * The NL2SQL service is the only store this product reads.
   *
   * `exclusive` stops the dashboard routes being called at all: they are keyed
   * by chat-registry ids, so `/api/dashboard/v1/sessions` answered 403 here and
   * the list showed "Failed to load" over threads the NL2SQL service was
   * holding perfectly well. Renaming and deleting go to the same service, and
   * `invitations: false` keeps the chat-registry invitation call — another 403 —
   * out of the page.
   *
   * The owner-only tabs read the same store with `show_guests_session`: other
   * users' threads on Users, widget visitors' on Widget.
   */
  const sessionSource = useMemo(
    () => ({
      // Keep the source exclusive while the service id is resolving. Without
      // this placeholder, the shared list briefly falls back to the
      // chat-registry `/api/dashboard/v1/sessions` endpoint on first render.
      // An empty key keeps its query disabled until the NL2SQL endpoint can be
      // addressed.
      key: nl2sqlId ? `${nl2sqlId}:${openedSessions.length}` : "",
      exclusive: true,
      invitations: false,
      load: async (tab: ConversationTab) => {
        if (!nl2sqlId) return [];
        const listed = await fetchNl2sqlSessions(nl2sqlId, {
          guests: isReadOnlyTab(tab),
        });
        if (tab === "widget") {
          return listed.filter((row) => row.from_chat_widget);
        }
        const threads = listed.filter((row) => !row.from_chat_widget);
        if (tab === "userHistory") return threads;
        // The dashboard tab also lists the threads this browser opened,
        // until the service returns them itself (see above).
        const seen = new Set(threads.map((row) => row.session_id));
        return [
          ...threads,
          ...openedSessions.filter((row) => !seen.has(row.session_id)),
        ];
      },
      // Both writes also update the ids this browser is holding, or a thread
      // deleted here came back on the next render with its old title — the
      // service had dropped it, this store had not.
      rename: async (sessionId: string, title: string) => {
        if (!nl2sqlId) return {};
        const result = await renameNl2sqlSession(nl2sqlId, sessionId, title);
        setOpenedSessions((current) => {
          const next = current.map((row) =>
            row.session_id === sessionId
              ? { ...row, session_title: title }
              : row,
          );
          writeOpenedSessions(nl2sqlId, next);
          return next;
        });
        return result;
      },
      remove: async (sessionId: string) => {
        if (!nl2sqlId) return {};
        // The id leaves this store first, and unconditionally. It is only a
        // crutch for the service's empty list, so a row the user asked to
        // remove has to leave it — otherwise a delete the service refuses
        // leaves a row that can never be removed. If the service still holds
        // the thread, its own list brings the row back.
        setOpenedSessions((current) => {
          const next = current.filter((row) => row.session_id !== sessionId);
          writeOpenedSessions(nl2sqlId, next);
          return next;
        });
        return deleteNl2sqlSession(nl2sqlId, sessionId);
      },
    }),
    [nl2sqlId, openedSessions],
  );

  const {
    sessionMessages,
    sessionId,
    messagesEndRef,
    messagesContainerRef,
    loading: chatLoading,
    chatId,
    error: chatError,
    callStreamAnswer,
    addMessage,
    resetChat,
  } = useChatStream(chatTransport);

  /**
   * The agent's own configuration, from the NL2SQL service — the starter
   * questions it offers and whether voice is available.
   *
   * Whether an answer shows sources, draws a chart or offers follow-ups is
   * deliberately *not* read here: those are resolved by the service from the
   * same configuration when the request omits them (see `toChatRequest`), so
   * mirroring them into the request body would only go stale the moment
   * Settings changed in another tab.
   */
  const { data: serviceConfig } = useQuery({
    queryKey: ["nl2sqlConfig", nl2sqlId],
    enabled: Boolean(nl2sqlId),
    refetchOnWindowFocus: false,
    queryFn: async () => {
      if (!nl2sqlId) return null;
      const response = await axios.get(
        `/nl2sql/api/v1/agents/${nl2sqlId}/config`,
      );
      return response.data;
    },
  });
  const serviceParams = serviceConfig?.config?.agent_params;
  const initialSuggestedQuestions: string[] =
    serviceParams?.suggested_questions ?? EMPTY_QUESTIONS;
  // The standalone product's Settings save these flags on the NL2SQL service.
  // Until that config has loaded, keep both controls unavailable rather than
  // falling back to the shared chat application's environment defaults.
  const voiceInputEnabled = Boolean(serviceParams?.voice_input_enabled);
  const voiceOutputEnabled = Boolean(serviceParams?.voice_output_enabled);

  const updateSelectedItemData = useCallback(
    (itemId: string | null, options?: { preserveNewChatView?: boolean }) => {
      setSelectedConversations((current) => ({
        ...current,
        [activeTab]: itemId,
      }));
      if (itemId) {
        previousSessionIdRef.current = "";
        if (!options?.preserveNewChatView) setIsNewChatViewActive(false);
      } else {
        setIsNewChatViewActive(true);
      }
    },
    [activeTab],
  );

  // A first question opens a session; follow it so the thread stops being a
  // "new chat" and the list shows the conversation that now exists.
  useEffect(() => {
    if (
      !sessionId ||
      sessionId === previousSessionIdRef.current ||
      selectedItemData ||
      sessionMessages.length === 0
    ) {
      return;
    }
    previousSessionIdRef.current = sessionId;
    const firstQuestion =
      sessionMessages.find((message) => message.role === "user")?.message ?? "";
    setOpenedSessions((current) => {
      if (current.some((row) => row.session_id === sessionId)) return current;
      const next = [
        {
          session_id: sessionId,
          session_title: firstQuestion.slice(0, 60),
          created_time: new Date().toISOString(),
        },
        ...current,
      ];
      writeOpenedSessions(nl2sqlId, next);
      return next;
    });
    queryClient
      .invalidateQueries({ queryKey: ["listData", activeTab, agentId] })
      .then(() => {
        setTimeout(() => {
          updateSelectedItemData(sessionId, { preserveNewChatView: true });
        }, 500);
      });
  }, [
    sessionId,
    selectedItemData,
    sessionMessages,
    activeTab,
    agentId,
    nl2sqlId,
    queryClient,
    updateSelectedItemData,
  ]);

  const handleNewChat = () => {
    updateSelectedItemData(null);
    previousSessionIdRef.current = "";
    resetChat();
    setInputValue("");
  };

  const handleSendMessage = useCallback(
    async (meta?: { viaVoice?: boolean }) => {
      if (!inputValue.trim()) return;
      try {
        addMessage(inputValue, meta?.viaVoice);
        setInputValue("");
        setMessageLoading(true);
        await callStreamAnswer({
          agent_id: agentId,
          session_id: sessionId || "",
          query: inputValue,
          no_of_chunks: 3,
          use_user_info: false,
          stream: true,
        });
      } finally {
        setMessageLoading(false);
      }
    },
    [inputValue, agentId, sessionId, addMessage, callStreamAnswer],
  );

  const showNewChat = activeTab === "dashboard" && isNewChatViewActive;

  /**
   * A session the agent never answered.
   *
   * The conversation exists and the question is in the query log, but the run
   * produced nothing, so the session comes back with no messages at all. Left
   * alone it renders as the "no messages yet" empty state, which reads as the
   * chat having lost the conversation rather than the agent having failed.
   *
   * Watches the cache entry `ConversationData` already fills rather than asking
   * for the session a second time. `useQuery` is the wrong tool here — it wants
   * a `queryFn` even when disabled, and logs an error for every render without
   * one — so this subscribes to the cache directly.
   */
  const turnsSnapshot = useCallback(
    () =>
      selectedItemData
        ? queryClient.getQueryData<unknown[]>(["itemDetails", selectedItemData])
        : undefined,
    [queryClient, selectedItemData],
  );
  const loadedTurns = useSyncExternalStore(
    useCallback(
      (onChange) => queryClient.getQueryCache().subscribe(onChange),
      [queryClient],
    ),
    turnsSnapshot,
    () => undefined,
  );
  const isUnanswered =
    Boolean(selectedItemData) &&
    Array.isArray(loadedTurns) &&
    loadedTurns.length === 0;
  return {
    agentId,
    nl2sqlId,
    activeTab,
    setActiveTab,
    readOnly,
    selectedItemData,
    selectedSessionMeta,
    setSelectedSessionMeta,
    isNewChatViewActive,
    showNewChat,
    inputValue,
    setInputValue,
    messageLoading,
    chatTransport,
    sessionSource,
    sessionMessages,
    sessionId,
    messagesEndRef,
    messagesContainerRef,
    chatLoading,
    chatId,
    chatError,
    initialSuggestedQuestions,
    voiceInputEnabled,
    voiceOutputEnabled,
    serviceParams,
    updateSelectedItemData,
    handleNewChat,
    handleSendMessage,
    isUnanswered,
  };
}

export type Nl2sqlChat = ReturnType<typeof useNl2sqlChat>;
