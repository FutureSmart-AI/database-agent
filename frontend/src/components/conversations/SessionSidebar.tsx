"use client";

import { useState } from "react";

import CollapseHandle from "@/components/CollapseHandle";
import Icon from "@/components/Icon";
import Modal from "@/components/ui/Modal";
import type { ConversationSession } from "@/platform/types/session";

import { filterSessions, groupSessions } from "./groupSessions";

interface SidebarTab {
  key: string;
  label: string;
  current: boolean;
  onSelect: () => void;
}

interface SessionSidebarProps {
  sessions: ConversationSession[];
  isLoading: boolean;
  error?: string | null;
  currentId: string | null;
  onSelect: (sessionId: string) => void;
  onNewChat: () => void;
  /**
   * My Conversations / Users / Widget.
   *
   * Not in the design artifact, which draws a single list — but the owner-only
   * monitoring tabs are existing functionality on this screen, and dropping
   * them to match the drawing would take a working feature away. Rendered
   * compactly so the rail still reads as the artifact's.
   */
  tabs: SidebarTab[];
  /**
   * Removes one conversation. Omitted on a list the reader may only watch —
   * the Users and Widget tabs are monitoring views, not the reader's threads.
   */
  onDelete?: (sessionId: string) => void;
  /** The database the agent routes questions to, shown in the footer. */
  database?: {
    name: string;
    engine: string;
    tableCount?: number;
    reachable: boolean;
  } | null;
  /**
   * Folds the rail down to a strip, remembered across visits.
   *
   * The list is dropped rather than hidden, so nothing under it can take a
   * click or a tab stop; the handle that brings it back rides the edge, as the
   * app shell's own sidebar handle does. Document Intelligence's rail collapses
   * the same way.
   */
  collapsed?: boolean;
  onToggleCollapsed?: () => void;
}

export default function SessionSidebar({
  sessions,
  isLoading,
  error,
  currentId,
  onSelect,
  onNewChat,
  tabs,
  onDelete,
  database,
  collapsed = false,
  onToggleCollapsed,
}: SessionSidebarProps) {
  const [query, setQuery] = useState("");
  // The conversation the reader asked to delete, held until they confirm: a
  // thread and its answers do not come back.
  const [pendingDelete, setPendingDelete] = useState<{
    id: string;
    title: string;
  } | null>(null);
  const groups = groupSessions(filterSessions(sessions, query));

  if (collapsed) {
    return (
      <aside
        aria-label="Conversations"
        className="relative flex w-11 flex-none flex-col items-center border-r border-n2s-line bg-n2s-card py-3"
      >
        <span className="text-[11.5px] tracking-wide text-n2s-ink-3 select-none [writing-mode:vertical-rl]">
          Conversations
        </span>
        {onToggleCollapsed && (
          <CollapseHandle
            collapsed
            onToggle={onToggleCollapsed}
            label="Expand conversations"
          />
        )}
      </aside>
    );
  }

  return (
    // `relative`, and never clipping: the collapse handle rides the right edge
    // and half of it hangs outside this panel.
    <aside
      aria-label="Conversations"
      className="relative flex w-63 flex-none flex-col border-r border-n2s-line bg-n2s-card"
    >
      {onToggleCollapsed && (
        <CollapseHandle
          collapsed={false}
          onToggle={onToggleCollapsed}
          label="Collapse conversations"
        />
      )}
      <div className="flex flex-col gap-2.5 px-3.5 pt-3.5 pb-2.5">
        <button
          type="button"
          onClick={onNewChat}
          className="flex w-full cursor-pointer items-center justify-center gap-1.5 rounded-[9px] border-0 bg-n2s-pri px-3 py-2.5 text-[13px] font-semibold text-white shadow-n2s-low hover:bg-n2s-pri-ink"
        >
          <Icon name="plusCircle" className="size-4" />
          New chat
        </button>
        {tabs.length > 1 && (
          <div
            role="tablist"
            aria-label="Conversation source"
            className="flex gap-0.5 rounded-lg bg-n2s-card-3 p-0.5"
          >
            {tabs.map((tab) => (
              <button
                key={tab.key}
                type="button"
                role="tab"
                aria-selected={tab.current}
                onClick={tab.onSelect}
                className={`flex-1 cursor-pointer truncate rounded-md px-2 py-1 text-[11px] font-semibold ${
                  tab.current
                    ? "bg-n2s-card text-n2s-ink shadow-n2s-low"
                    : "bg-transparent text-n2s-ink-3"
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
        )}
        <div className="flex items-center gap-1.5 rounded-lg border border-n2s-line bg-n2s-card-2 px-2.5 py-1.5">
          <Icon
            name="search"
            className="size-3 text-n2s-ink-3"
            strokeWidth={2}
          />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search conversations"
            aria-label="Search conversations"
            className="w-full border-0 bg-transparent text-xs text-n2s-ink outline-none placeholder:text-n2s-ink-3"
          />
        </div>
      </div>

      <div className="flex flex-1 flex-col gap-3.5 overflow-y-auto px-2 pb-3">
        {error ? (
          <p className="px-2 text-xs text-n2s-err">{error}</p>
        ) : isLoading ? (
          <div className="flex flex-col gap-1.5 px-2 pt-1">
            {[0, 1, 2].map((row) => (
              <div
                key={row}
                className="h-7 animate-pulse rounded-lg bg-n2s-card-3"
              />
            ))}
          </div>
        ) : !groups.length ? (
          <p className="px-2 pt-1 text-xs text-n2s-ink-3">
            {query.trim()
              ? `No conversation matches “${query.trim()}”.`
              : "No conversations yet."}
          </p>
        ) : (
          groups.map((group) => (
            <div key={group.label} className="flex flex-col gap-0.5">
              <div className="px-2 py-1 text-[10.5px] font-bold tracking-[0.07em] text-n2s-ink-3 uppercase">
                {group.label}
              </div>
              {group.items.map((session) => {
                const current = session.session_id === currentId;
                const title = session.session_title || "Untitled conversation";
                return (
                  <div
                    key={session.session_id}
                    className={`group flex items-center gap-1 rounded-lg pr-1 ${
                      current ? "bg-n2s-pri-wash" : "hover:bg-n2s-card-3"
                    }`}
                  >
                    <button
                      type="button"
                      aria-current={current ? "true" : undefined}
                      onClick={() => onSelect(session.session_id)}
                      className={`flex min-w-0 flex-1 cursor-pointer items-center gap-2 rounded-lg border-0 bg-transparent px-2.5 py-2 text-left text-[12.5px] leading-snug ${
                        current
                          ? "font-semibold text-n2s-pri-ink"
                          : "font-medium text-n2s-ink-2"
                      }`}
                    >
                      <span
                        className={`size-1 flex-none rounded-full ${
                          current ? "bg-n2s-pri" : "bg-n2s-line"
                        }`}
                      />
                      <span className="truncate">{title}</span>
                    </button>
                    {onDelete && (
                      <button
                        type="button"
                        aria-label={`Delete "${title}"`}
                        onClick={() =>
                          setPendingDelete({
                            id: session.session_id,
                            title,
                          })
                        }
                        className="grid size-6 flex-none cursor-pointer place-items-center rounded-md border-0 bg-transparent text-n2s-ink-3 opacity-0 group-hover:opacity-100 hover:text-n2s-err focus-visible:opacity-100"
                      >
                        <Icon name="trash" className="size-3.5" />
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          ))
        )}
      </div>

      {pendingDelete && (
        <Modal
          title="Delete this conversation?"
          sub={`“${pendingDelete.title}” and every answer in it are removed. This cannot be undone.`}
          onClose={() => setPendingDelete(null)}
          footer={
            <>
              <button
                type="button"
                onClick={() => setPendingDelete(null)}
                className="cursor-pointer rounded-lg border border-n2s-line bg-n2s-card px-3 py-2 text-[13px] font-semibold text-n2s-ink-2 hover:bg-n2s-card-3"
              >
                Keep it
              </button>
              <button
                type="button"
                onClick={() => {
                  onDelete?.(pendingDelete.id);
                  setPendingDelete(null);
                }}
                className="cursor-pointer rounded-lg border-0 bg-n2s-err px-3 py-2 text-[13px] font-semibold text-white hover:opacity-90"
              >
                Delete
              </button>
            </>
          }
        >
          <p className="m-0 text-[13px] text-n2s-ink-2">
            The thread leaves this list and the agent&apos;s history for
            everyone who can see it.
          </p>
        </Modal>
      )}

      {database && (
        <div className="flex items-center gap-2 border-t border-n2s-line px-3.5 py-3">
          <span
            className={`size-[7px] flex-none rounded-full ${
              database.reachable ? "animate-pulse bg-n2s-ok" : "bg-n2s-err"
            }`}
          />
          <div className="min-w-0">
            <div className="truncate text-[11.5px] font-semibold text-n2s-ink">
              {database.name}
            </div>
            <div className="text-[10.5px] text-n2s-ink-3">
              {database.engine}
              {database.tableCount !== undefined &&
                ` · ${database.tableCount} ${database.tableCount === 1 ? "table" : "tables"}`}
            </div>
          </div>
        </div>
      )}
    </aside>
  );
}
