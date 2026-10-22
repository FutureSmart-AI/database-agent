"use client";

import Icon from "@/components/Icon";

interface ChatEmptyStateProps {
  /** The database the agent will run the query against, when it is known. */
  databaseName?: string;
  suggestions: string[];
  onPick: (question: string) => void;
}

export default function ChatEmptyState({
  databaseName,
  suggestions,
  onPick,
}: ChatEmptyStateProps) {
  return (
    <div className="flex flex-1 flex-col items-center overflow-y-auto px-6 py-8">
      <div className="my-auto flex w-full max-w-160 flex-col gap-5">
        <div className="flex flex-col gap-2">
          <div className="grid size-10.5 place-items-center rounded-xl bg-n2s-pri-wash text-n2s-pri">
            <Icon name="db" className="size-5" />
          </div>
          <h2 className="font-display text-[22px] font-bold text-n2s-ink">
            Ask a question about your data in plain English.
          </h2>
          <p className="m-0 max-w-[52ch] text-[13.5px] leading-relaxed text-pretty text-n2s-ink-2">
            The agent writes the SQL, runs it
            {databaseName ? (
              <>
                {" against "}
                <span className="font-mono text-[12.5px]">{databaseName}</span>
              </>
            ) : (
              " against your database"
            )}
            , and shows you both the answer and the query behind it.
          </p>
        </div>

        {suggestions.length > 0 && (
          <div className="flex flex-col gap-2">
            <div className="text-[10.5px] font-bold tracking-[0.07em] text-n2s-ink-3 uppercase">
              Try one of these
            </div>
            <div className="flex flex-wrap gap-2">
              {suggestions.map((question) => (
                <button
                  key={question}
                  type="button"
                  onClick={() => onPick(question)}
                  className="cursor-pointer rounded-full border border-n2s-line bg-n2s-card px-3 py-2 text-[12.5px] font-medium text-n2s-ink-2 hover:border-n2s-pri hover:bg-n2s-pri-wash hover:text-n2s-pri-ink"
                >
                  {question}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
