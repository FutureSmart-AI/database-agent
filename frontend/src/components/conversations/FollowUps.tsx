"use client";

interface FollowUpsProps {
  questions: string[];
  onPick: (question: string) => void;
  /** No question can be sent right now, so none is suggested. */
  disabled?: boolean;
}

/** The agent's suggested next questions, as dashed pills under an answer. */
export default function FollowUps({
  questions,
  onPick,
  disabled = false,
}: FollowUpsProps) {
  if (!questions.length || disabled) return null;

  return (
    <nav
      aria-label="Suggested follow-up questions"
      className="flex flex-wrap gap-1.5 pt-1"
    >
      {questions.map((question) => (
        <button
          key={question}
          type="button"
          onClick={() => onPick(question)}
          className="cursor-pointer rounded-full border border-dashed border-n2s-line bg-transparent px-2.5 py-1.5 text-xs text-n2s-ink-2 hover:border-solid hover:border-n2s-pri hover:text-n2s-pri-ink"
        >
          {question}
        </button>
      ))}
    </nav>
  );
}
