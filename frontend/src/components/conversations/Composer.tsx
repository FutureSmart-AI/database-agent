"use client";

import { useRef } from "react";

import MessageBox from "@/platform/components/conversations/MessageBox";

interface ComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSend: (meta?: { viaVoice?: boolean }) => void;
  voiceInputEnabled?: boolean;
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
}: ComposerProps) {
  const inputRef = useRef<{ focus: () => void }>({ focus: () => {} });

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
