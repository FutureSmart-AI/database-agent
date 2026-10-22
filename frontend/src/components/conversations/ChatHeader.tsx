"use client";

import Icon from "@/components/Icon";

interface ChatHeaderProps {
  title: string;
  subtitle?: string;
  /** Null while the agent's databases are still loading. */
  connected: boolean | null;
  connectionNote?: string;
  /** Whether the schema panel is open, when there is a database to show. */
  schemaOpen?: boolean;
  onToggleSchema?: () => void;
}

/** Title, agent line and connection state above the thread. */
export default function ChatHeader({
  title,
  subtitle,
  connected,
  connectionNote,
  schemaOpen,
  onToggleSchema,
}: ChatHeaderProps) {
  return (
    <header className="flex flex-none items-center gap-3 border-b border-n2s-line bg-n2s-card px-5 py-3">
      <div className="min-w-0">
        <h1 className="truncate font-display text-[15px] font-bold text-n2s-ink">
          {title}
        </h1>
        {subtitle && (
          <div className="mt-px text-[11.5px] text-n2s-ink-3">{subtitle}</div>
        )}
      </div>
      <div className="flex-1" />
      {connected !== null && (
        <span
          title={connectionNote}
          className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold ${
            connected
              ? "bg-n2s-ok-wash text-n2s-ok ring-1 ring-n2s-ok/20 ring-inset"
              : "bg-n2s-err-wash text-n2s-err ring-1 ring-n2s-err/20 ring-inset"
          }`}
        >
          <Icon
            name={connected ? "chk" : "warn"}
            className="size-3"
            strokeWidth={2.6}
          />
          {connected ? "Connected" : "Not reachable"}
        </span>
      )}
      {onToggleSchema && (
        <button
          type="button"
          onClick={onToggleSchema}
          aria-pressed={Boolean(schemaOpen)}
          className={`inline-flex cursor-pointer items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-semibold ${
            schemaOpen
              ? "border-n2s-pri bg-n2s-pri-wash text-n2s-pri-ink"
              : "border-n2s-line bg-n2s-card text-n2s-ink-2 hover:bg-n2s-card-2 hover:text-n2s-ink"
          }`}
        >
          <Icon name="db" className="size-3" strokeWidth={1.9} />
          Schema
        </button>
      )}
    </header>
  );
}
