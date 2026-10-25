"use client";

import { useEffect, useRef } from "react";

import MessageBox from "@/platform/components/conversations/MessageBox";

interface ComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSend: (meta?: { viaVoice?: boolean }) => void;
  voiceInputEnabled?: boolean;
  /**
   * Why no question can be sent right now (a used-up free allowance). The
   * input is replaced by this note, so the reason is read before typing rather
   * than after a refused run.
   */
  blockedNote?: string | null;
  /**
   * Bumped when a suggested question is put into the input: the input takes
   * focus with the caret at the end, so Enter sends it. Without this, focus
   * stayed on the suggestion button and Enter did nothing.
   */
  focusSignal?: number;
}

/**
 * The composer, in the artifact's frame.
 *
 * The input itself is the agent UI's `MessageBox` rather than a new textarea:
 * it carries the streaming speech-to-text stack — the realtime socket, the
 * language selector, the recording meter and the microphone-permission gate
 * that a host page's `Permissions-Policy` can veto. Re-deriving any of that
 * here would quietly drop behaviour that took several fixes to get right.
 */
export default function Composer({
  value,
  onChange,
  onSend,
  voiceInputEnabled,
  blockedNote,
  focusSignal = 0,
}: ComposerProps) {
  const inputRef = useRef<{ focus: () => void }>({ focus: () => {} });

  useEffect(() => {
    if (focusSignal > 0) inputRef.current?.focus();
  }, [focusSignal]);

  if (blockedNote) {
    return (
      <div className="flex-none px-6 pt-3.5 pb-5">
        <div
          role="status"
          className="mx-auto max-w-205 rounded-xl border border-n2s-line bg-n2s-card-2 px-4 py-3 text-center text-[12.5px] text-n2s-ink-2"
        >
          {blockedNote}
        </div>
      </div>
    );
  }

  return (
    <div className="flex-none px-6 pt-3.5 pb-5">
      <div className="mx-auto flex max-w-205 flex-col gap-2">
        <MessageBox
          ref={inputRef}
          inputValue={value}
          setInputValue={onChange}
          getBotAnswer={onSend}
          voiceInputEnabled={voiceInputEnabled}
        />
        {/* The keyboard hint is `MessageBox`'s own — repeating it here printed
            it twice under the input. */}
        <div className="text-[11px] text-n2s-ink-3">
          The agent runs read-only queries. Verify results before acting on
          them.
        </div>
      </div>
    </div>
  );
}
