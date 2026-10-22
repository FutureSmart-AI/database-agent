/** One row of a conversation list, as the NL2SQL sessions route answers it. */
export interface ConversationSession {
  session_id: string;
  session_title: string;
  created_time: string;
  // Present only on the owner/admin monitoring tabs:
  user_id?: string | null;
  from_chat_widget?: boolean;
  role?: "owner" | "editor" | "viewer" | null;
  source?: string | null;
}
