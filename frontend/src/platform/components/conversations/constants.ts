export type ConversationTab = "dashboard" | "userHistory" | "widget";

// "dashboard" = the signed-in user's own chats (interactive, all roles).
// "userHistory" / "widget" = owner/admin-only, read-only monitoring views.
export const MY_CONVERSATIONS_TAB = {
  key: "dashboard",
  label: "My Conversations",
} as const;

// Owner/Admin see all three tabs; everyone else sees only their own chats.
export const OWNER_CONVERSATION_TABS = [
  MY_CONVERSATIONS_TAB,
  { key: "userHistory", label: "Users" },
  { key: "widget", label: "Widget" },
] as const;

export const CONVERSATION_FILTERS_TABS = [MY_CONVERSATIONS_TAB];

// How many (newest-first) sessions to render initially; more load on scroll.
// Keeps the list snappy for owner/admin monitoring large conversation volumes.
export const SESSIONS_PAGE_SIZE = 30;

// Read-only tabs never allow sending, editing, deleting, or feedback.
export const READ_ONLY_TABS: ConversationTab[] = ["userHistory", "widget"];

export const isReadOnlyTab = (tab: ConversationTab): boolean =>
  READ_ONLY_TABS.includes(tab);
