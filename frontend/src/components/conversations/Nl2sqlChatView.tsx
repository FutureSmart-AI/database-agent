"use client";

import { useMemo, useState } from "react";

import { useQuery, useQueryClient } from "@tanstack/react-query";

import { fetchDatabases, fetchTables } from "@/data/databases";
import { useCollapsed } from "@/lib/useCollapsed";
import {
  isReadOnlyTab,
  MY_CONVERSATIONS_TAB,
  type ConversationTab,
} from "@/platform/components/conversations/constants";
import { useToast } from "@/platform/components/ToastContext";

import ChatEmptyState from "./ChatEmptyState";
import ChatHeader from "./ChatHeader";
import Composer from "./Composer";
import Nl2sqlSessionThread from "./Nl2sqlSessionThread";
import SchemaPanel from "./SchemaPanel";
import SessionSidebar from "./SessionSidebar";
import Thread from "./Thread";
import { useNl2sqlChat } from "./useNl2sqlChat";

/**
 * The NL2SQL conversations screen, in the product's design artifact.
 *
 * All of the screen's plumbing lives in `useNl2sqlChat`; this file is the
 * layout the artifact specifies — sessions rail, header, thread and composer.
 */
export default function Nl2sqlChatView() {
  const chat = useNl2sqlChat();
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const [suggestionDraft, setSuggestionDraft] = useState<string | null>(null);
  // Closed to begin with: the thread is what the screen is for, and the schema
  // is the reference you reach for while writing a question.
  const [schemaOpen, setSchemaOpen] = useState(false);
  // The rail folds away to a strip, and stays folded on the next visit: a
  // person reading one long answer wants the width, and asking for it again on
  // every visit is the part that would wear thin.
  const { collapsed: listCollapsed, toggle: toggleList } =
    useCollapsed("conversation-list");

  const sessions = useQuery({
    queryKey: ["nl2sqlSessions", chat.sessionSource.key, chat.activeTab],
    enabled: Boolean(chat.nl2sqlId),
    queryFn: () => chat.sessionSource.load(chat.activeTab),
  });

  // The database the agent routes questions to: the footer names it and the
  // header's pill reports whether it is actually reachable, rather than
  // claiming "Connected" unconditionally.
  const databases = useQuery({
    queryKey: ["databases", chat.nl2sqlId],
    enabled: Boolean(chat.nl2sqlId),
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
    queryFn: () => fetchDatabases(chat.nl2sqlId as string),
  });
  const database = useMemo(
    () => databases.data?.find((entry) => entry.active) ?? databases.data?.[0],
    [databases.data],
  );

  const tables = useQuery({
    queryKey: ["tables", chat.nl2sqlId, database?.db_id],
    enabled: Boolean(chat.nl2sqlId && database?.db_id),
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
    queryFn: () =>
      fetchTables(chat.nl2sqlId as string, database?.db_id as string),
  });

  /**
   * Tables this agent is configured to exclude.
   *
   * Settings marks them under Tables & visibility, and an answer that read one
   * anyway has its query and rows withheld from the turn — benchmark TC60 found
   * an excluded table's SQL and rows drawn under the answer's own "restricted"
   * sentence. The flags are already on screen for the schema panel; this reuses
   * them rather than asking again.
   */
  const excludedTables = useMemo(
    () =>
      (tables.data ?? [])
        .filter((table) => !table.is_included)
        .map((table) => table.table_name),
    [tables.data],
  );

  /**
   * Whether an answer may show its SQL and its rows.
   *
   * A stored turn comes back carrying both whatever the settings say, so the
   * gate is applied here rather than trusted to the payload.
   *
   * The switches are the agent's own, each read for what it names:
   * `show_db_result` for the rows, `show_sql_query` for the query. Gating both
   * on `debug_info` as well — as this screen used to — hid the result card on
   * every agent in the workspace but one, because `debug_info` defaults to
   * false while both display switches default to true. `debug_info` is what it
   * says: the extra diagnostics (the refined question, the reported steps),
   * which is all it gates now.
   */
  // Settings → Answers writes `show_sql_query` and `show_db_result`.
  const showQuery = chat.serviceParams?.show_sql_query !== false;
  const showResults = chat.serviceParams?.show_db_result !== false;
  // Parsing the answer's NL2SQL block at all: worth doing when either half of
  // it may be shown, since the run trace is drawn from the same facts.
  const showSources = showQuery || showResults;
  /**
   * The untouched payload, behind the card's Raw tab.
   *
   * This screen is the owner's own console: it already shows the query, the
   * rows and the run log, so the response that produced them is not a further
   * disclosure. It used to be gated on `raw_response`, a chat-registry flag no
   * NL2SQL agent carries, which meant the tab existed for nobody and any field
   * the card does not draw — a chart palette, an axis's source column, the ids
   * — had nowhere to be read. An agent that explicitly sets the flag to false
   * is still honoured.
   */
  const rawEnabled = chat.serviceParams?.raw_response !== false;

  /**
   * One list: the signed-in account's own conversations.
   *
   * The owner-only Users and Widget lists are not offered here — they are
   * monitoring views, and Share → Activity already reads both stores with the
   * filters, the search and the turn viewer that monitoring wants. Keeping a
   * second, thinner copy of them in the chat rail put two answers to "whose
   * conversations am I looking at?" on the same screen. Document Intelligence
   * draws its rail the same way.
   *
   * `activeTab` therefore stays "dashboard", which is what makes every
   * `isReadOnlyTab` check below false: this rail is never a read-only list.
   */
  const tabs = [MY_CONVERSATIONS_TAB];

  return (
    <div className="flex h-full min-h-0 bg-n2s-plane">
      <SessionSidebar
        sessions={sessions.data ?? []}
        isLoading={sessions.isLoading}
        error={sessions.error ? "Could not load conversations." : null}
        currentId={chat.selectedItemData}
        onSelect={(id) => chat.updateSelectedItemData(id)}
        onNewChat={chat.handleNewChat}
        tabs={tabs.map((tab) => ({
          key: tab.key as ConversationTab,
          label: tab.label,
          current: chat.activeTab === tab.key,
          onSelect: () => chat.setActiveTab(tab.key as ConversationTab),
        }))}
        onDelete={
          isReadOnlyTab(chat.activeTab)
            ? undefined
            : async (sessionId) => {
                try {
                  const result = await chat.sessionSource.remove(sessionId);
                  // The open thread has just been deleted: go back to a new
                  // chat rather than leaving its answers on screen.
                  if (sessionId === chat.selectedItemData) chat.handleNewChat();
                  await queryClient.invalidateQueries({
                    queryKey: ["nl2sqlSessions"],
                  });
                  toast.success(result?.message || "Conversation deleted");
                } catch {
                  // Reported by the shared axios interceptor.
                }
              }
        }
        database={
          database
            ? {
                name: database.db_name,
                engine: database.db_engine,
                tableCount: tables.data?.length,
                reachable: database.reachable,
              }
            : null
        }
        collapsed={listCollapsed}
        onToggleCollapsed={toggleList}
      />

      {/* Not a <main>: the app shell already owns the page's main landmark,
          and nesting a second one leaves a screen reader with two. */}
      <div className="flex min-w-0 flex-1 flex-col">
        <ChatHeader
          title={
            chat.showNewChat
              ? "New conversation"
              : (chat.selectedSessionMeta?.session_title ?? "Conversation")
          }
          subtitle={database ? `Asking ${database.db_name}` : undefined}
          connected={database ? database.reachable : null}
          connectionNote={
            database?.reachable
              ? `${database.db_name} answered its last connection check.`
              : "The agent could not reach this database — check it under Settings."
          }
          schemaOpen={schemaOpen}
          onToggleSchema={
            database ? () => setSchemaOpen((open) => !open) : undefined
          }
        />

        {/* The thread and the schema sit side by side under the header, as in
            the artifact: the reference stays open while the thread scrolls. */}
        <div className="flex min-h-0 flex-1">
          <div className="flex min-w-0 flex-1 flex-col">
            {chat.isUnanswered && (
              <div className="flex-none border-b border-n2s-amber/25 bg-n2s-amber-wash px-6 py-3">
                <p className="m-0 text-sm font-semibold text-n2s-amber">
                  This conversation has no saved answer.
                </p>
                <p className="m-0 mt-0.5 text-sm text-n2s-ink-2">
                  The question was asked, but the agent never produced an
                  answer, so there is nothing stored to show. Check the agent
                  can reach its databases under Settings, then ask again.
                </p>
              </div>
            )}

            {chat.showNewChat ? (
              <>
                {chat.sessionMessages.length ? (
                  <Thread
                    messages={chat.sessionMessages}
                    loading={chat.chatLoading}
                    streaming={chat.messageLoading}
                    sessionId={chat.sessionId}
                    chatId={chat.chatId}
                    activeTab="newchat"
                    nl2sqlServiceId={chat.nl2sqlId}
                    showSources={showSources}
                    showQuery={showQuery}
                    showResults={showResults}
                    rawEnabled={rawEnabled}
                    voiceOutputEnabled={chat.voiceOutputEnabled}
                    excludedTables={excludedTables}
                    initialSuggestedQuestions={chat.initialSuggestedQuestions}
                    onPickQuestion={chat.setInputValue}
                    error={chat.chatError}
                  />
                ) : (
                  <ChatEmptyState
                    databaseName={database?.db_name}
                    suggestions={chat.initialSuggestedQuestions}
                    onPick={(question) => {
                      chat.setInputValue(question);
                      setSuggestionDraft(question);
                    }}
                  />
                )}
                <Composer
                  key={suggestionDraft ?? "composer"}
                  value={chat.inputValue}
                  onChange={chat.setInputValue}
                  onSend={chat.handleSendMessage}
                  voiceInputEnabled={chat.voiceInputEnabled}
                />
              </>
            ) : chat.selectedItemData ? (
              <Nl2sqlSessionThread
                key={chat.selectedItemData}
                sessionId={chat.selectedItemData}
                activeTab={chat.activeTab}
                readOnly={isReadOnlyTab(chat.activeTab)}
                chatTransport={chat.chatTransport}
                nl2sqlServiceId={chat.nl2sqlId}
                agentId={chat.agentId}
                showSources={showSources}
                showQuery={showQuery}
                showResults={showResults}
                rawEnabled={rawEnabled}
                voiceInputEnabled={chat.voiceInputEnabled}
                voiceOutputEnabled={chat.voiceOutputEnabled}
                excludedTables={excludedTables}
                initialSuggestedQuestions={chat.initialSuggestedQuestions}
              />
            ) : (
              <div className="flex flex-1 items-center justify-center p-6 text-center text-sm text-n2s-ink-3">
                {isReadOnlyTab(chat.activeTab)
                  ? "Select a conversation to view its full history."
                  : "Select a conversation or start a new chat."}
              </div>
            )}
          </div>

          {schemaOpen && database && (
            <SchemaPanel
              databaseName={database.db_name}
              tables={tables.data ?? []}
              isLoading={tables.isLoading}
              error={
                tables.error ? "Could not read this database's tables." : null
              }
              onClose={() => setSchemaOpen(false)}
            />
          )}
        </div>
      </div>
    </div>
  );
}
