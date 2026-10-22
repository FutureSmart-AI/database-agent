"use client";

import { useState } from "react";

import Icon from "@/components/Icon";
import type { DbTable } from "@/data/databases";

interface SchemaPanelProps {
  /** The database the tables belong to, named in the panel's header. */
  databaseName?: string;
  tables: DbTable[];
  isLoading: boolean;
  error?: string | null;
  onClose: () => void;
}

/**
 * The tables behind the answers, beside the thread.
 *
 * The artifact draws each table opening onto its columns and their types. The
 * service has no column-level route — `…/databases/{db_id}/tables` reports a
 * name, a description, a count and whether the agent may read it — so a table
 * opens onto what the agent actually knows about it instead of inventing a
 * column list the screen cannot stand behind.
 */
export default function SchemaPanel({
  databaseName,
  tables,
  isLoading,
  error,
  onClose,
}: SchemaPanelProps) {
  const [openTable, setOpenTable] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  const needle = query.trim().toLowerCase();
  const shown = needle
    ? tables.filter(
        (table) =>
          table.table_name.toLowerCase().includes(needle) ||
          table.description.toLowerCase().includes(needle),
      )
    : tables;

  return (
    <aside
      aria-label="Database schema"
      className="flex w-68 flex-none flex-col border-l border-n2s-line bg-n2s-card"
    >
      <div className="flex items-center gap-2 border-b border-n2s-line px-3.5 py-3">
        <h2 className="text-[12.5px] font-bold text-n2s-ink">Schema</h2>
        {databaseName && (
          <span className="truncate font-mono text-[10.5px] text-n2s-ink-3">
            {databaseName}
          </span>
        )}
        <div className="flex-1" />
        <button
          type="button"
          onClick={onClose}
          aria-label="Hide schema"
          className="grid cursor-pointer place-items-center border-0 bg-transparent text-n2s-ink-3 hover:text-n2s-ink"
        >
          <Icon name="x" className="size-3.5" strokeWidth={2} />
        </button>
      </div>

      {tables.length > 0 && (
        <div className="flex items-center gap-1.5 border-b border-n2s-line px-3 py-2">
          <Icon
            name="search"
            className="size-3 text-n2s-ink-3"
            strokeWidth={2}
          />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search tables"
            aria-label="Search tables"
            className="w-full border-0 bg-transparent text-xs text-n2s-ink outline-none placeholder:text-n2s-ink-3"
          />
        </div>
      )}

      <div className="flex-1 overflow-y-auto p-2">
        {error ? (
          <p className="px-2 py-1 text-xs text-n2s-err">{error}</p>
        ) : isLoading ? (
          <div className="flex flex-col gap-1.5 px-1 pt-1">
            {[0, 1, 2, 3].map((row) => (
              <div
                key={row}
                className="h-7 animate-pulse rounded-lg bg-n2s-card-3"
              />
            ))}
          </div>
        ) : !shown.length ? (
          <p className="px-2 py-1 text-xs text-n2s-ink-3">
            {needle
              ? `No table matches “${query.trim()}”.`
              : "This database exposes no tables to the agent."}
          </p>
        ) : (
          shown.map((table) => {
            const open = openTable === table.table_name;
            return (
              <div key={table.table_name} className="flex flex-col">
                <button
                  type="button"
                  aria-expanded={open}
                  onClick={() => setOpenTable(open ? null : table.table_name)}
                  className={`flex cursor-pointer items-center gap-2 rounded-lg border-0 px-2.5 py-2 text-left hover:bg-n2s-card-3 ${
                    open ? "bg-n2s-card-2" : "bg-transparent"
                  }`}
                >
                  <Icon
                    name="caretRight"
                    className={`size-3 flex-none text-n2s-ink-3 transition-transform duration-150 ${
                      open ? "rotate-90" : ""
                    }`}
                    strokeWidth={2.4}
                  />
                  <span
                    className={`truncate font-mono text-xs ${
                      open ? "font-semibold text-n2s-pri-ink" : "text-n2s-ink-2"
                    }`}
                  >
                    {table.table_name}
                  </span>
                  {!table.is_included && (
                    <span
                      title="Excluded from answers"
                      className="flex-none text-n2s-amber"
                    >
                      <Icon name="eyeOff" className="size-3" />
                    </span>
                  )}
                  <div className="flex-1" />
                  <span className="flex-none text-[10.5px] whitespace-nowrap text-n2s-ink-3">
                    {table.column_count}{" "}
                    {table.column_count === 1 ? "column" : "columns"}
                  </span>
                </button>
                {open && (
                  <div className="flex flex-col gap-1 pt-0.5 pb-2 pl-7 pr-2">
                    <p className="m-0 text-[11.5px] leading-relaxed text-pretty text-n2s-ink-2">
                      {table.description ||
                        "No description — the agent goes on the table and column names alone. Describe it under Settings → Databases."}
                    </p>
                    {!table.is_included && (
                      <p className="m-0 text-[11px] text-n2s-amber">
                        Excluded from answers, so questions never reach this
                        table.
                      </p>
                    )}
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </aside>
  );
}
