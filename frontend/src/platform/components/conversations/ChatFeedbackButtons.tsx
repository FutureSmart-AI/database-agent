import { useEffect, useState } from "react";

import { ThumbsDown, ThumbsUp } from "lucide-react";

import axios from "@/platform/utils/axios";

import { useToast } from "../ToastContext";

interface ChatFeedbackButtonsProps {
  sessionId: string;
  chatId: string | null;
  userFeedback: string | null;
  activeTab: string;
  readOnly?: boolean;
  /** The agent the answer came from; feedback goes to its own route. */
  nl2sqlServiceId: string | null;
  /** The question that produced this answer — required by the NL2SQL route. */
  userQuery?: string;
  /** The SQL the answer ran, as far as the message carries it. */
  generatedQuery?: string;
}

const ChatFeedbackButtons = ({
  sessionId,
  chatId,
  userFeedback,
  activeTab,
  readOnly,
  nl2sqlServiceId,
  userQuery,
  generatedQuery,
}: ChatFeedbackButtonsProps) => {
  const { toast } = useToast();
  const [feedbackType, setFeedbackType] = useState<
    "positive" | "negative" | null
  >(null);
  const [isLoading, setIsLoading] = useState(false);
  useEffect(() => {
    if (userFeedback !== null) {
      setFeedbackType(userFeedback === "positive" ? "positive" : "negative");
    }
  }, [userFeedback]);

  const submitFeedback = async (feedback: boolean) => {
    if (userFeedback !== null || !chatId || !nl2sqlServiceId) return;
    setIsLoading(true);
    try {
      // NL2SQL takes the question and the SQL with a "correct"/"incorrect"
      // label, rather than a bare boolean.
      const res = await axios.post(
        `/nl2sql/api/v1/agents/${nl2sqlServiceId}/feedback`,
        {
          session_id: sessionId,
          chat_id: chatId,
          user_query: userQuery ?? "",
          generated_query: generatedQuery ?? "",
          label: feedback ? "correct" : "incorrect",
        },
      );
      setFeedbackType(feedback ? "positive" : "negative");
      if (res?.data?.message) toast.success(res.data.message);
    } catch (err) {
      toast.error("Failed to submit feedback");
    } finally {
      setIsLoading(false);
    }
  };

  // Read-only monitoring tabs: show feedback as a static badge, never buttons.
  if (readOnly) {
    if (feedbackType === null) return null;
    const positive = feedbackType === "positive";
    return (
      <span
        className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-medium ${
          positive
            ? "bg-emerald-50 text-emerald-700"
            : "bg-rose-50 text-rose-700"
        }`}
      >
        {positive ? (
          <ThumbsUp className="size-3" />
        ) : (
          <ThumbsDown className="size-3" />
        )}
        {positive ? "Positive feedback" : "Negative feedback"}
      </span>
    );
  }

  return (
    <div className="flex gap-2">
      {feedbackType !== "negative" && (
        <span className="group relative inline-flex">
          <button
            type="button"
            aria-label="Like"
            title={
              activeTab === "widget"
                ? "changes to widget responses are not allowed"
                : feedbackType === "positive"
                  ? "Liked"
                  : "Like"
            }
            onClick={() => submitFeedback(true)}
            disabled={
              feedbackType !== null || isLoading || activeTab === "widget"
            }
            className={`inline-flex cursor-pointer items-center bg-transparent text-slate-700 hover:text-slate-900 disabled:cursor-not-allowed disabled:opacity-50 ${
              feedbackType === "positive" ? "text-emerald-600!" : ""
            }`}
          >
            <ThumbsUp className="size-4" />
          </button>
          <span className="pointer-events-none absolute -top-7 left-1/2 -translate-x-1/2 whitespace-nowrap rounded-md bg-slate-900 px-2 py-0.5 text-[10px] font-medium text-white opacity-0 shadow-sm transition-opacity group-hover:opacity-100">
            {activeTab === "widget"
              ? "changes to widget responses are not allowed"
              : feedbackType === "positive"
                ? "Liked"
                : "Like"}
          </span>
        </span>
      )}
      {feedbackType !== "positive" && (
        <span className="group relative inline-flex">
          <button
            type="button"
            aria-label="Dislike"
            title={
              activeTab === "widget"
                ? "changes to widget responses are not allowed"
                : feedbackType !== null
                  ? "Disliked"
                  : "Dislike"
            }
            onClick={() => submitFeedback(false)}
            disabled={
              feedbackType !== null || isLoading || activeTab === "widget"
            }
            className={`inline-flex cursor-pointer items-center bg-transparent text-slate-700 hover:text-slate-900 disabled:cursor-not-allowed disabled:opacity-50 ${
              feedbackType === "negative" ? "text-rose-600!" : ""
            }`}
          >
            <ThumbsDown className="size-4" />
          </button>
          <span className="pointer-events-none absolute -top-7 left-1/2 -translate-x-1/2 whitespace-nowrap rounded-md bg-slate-900 px-2 py-0.5 text-[10px] font-medium text-white opacity-0 shadow-sm transition-opacity group-hover:opacity-100">
            {activeTab === "widget"
              ? "changes to widget responses are not allowed"
              : feedbackType !== null
                ? "Disliked"
                : "Dislike"}
          </span>
        </span>
      )}
    </div>
  );
};

export default ChatFeedbackButtons;
