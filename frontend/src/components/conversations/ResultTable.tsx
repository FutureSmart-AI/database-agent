"use client";

import { useEffect, useMemo, useState } from "react";

import {
  NUMERIC_COLUMN_TYPE,
  RESULT_PAGE_SIZE as PAGE_SIZE,
} from "./constants";

interface ResultTableProps {
  /** Rows to draw — already narrowed by the card's filter box. */
  rows: Record<string, unknown>[];
  /** Visible columns, in order — the card owns which are hidden. */
  columns: string[];
  /**
   * The type the service declared per column, where it declared one.
   *
   * `db_result.columns` carries `{ name, type }`; the table used to see only
   * the names and judge every column by the values that happened to land in
   * it, so an all-integer id column read as a number and a numeric column of
   * strings sorted alphabetically.
   */
  types?: Record<string, string | undefined>;
  /** How many rows the result had before the filter, for the footer note. */
  totalRows: number;
  /** The card's filter box, for the "nothing matched" row. */
  query: string;
}

/** Cell text for any JSON value the service can put in a column. */
export function display(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/**
 * Values that are read rather than spoken: ids, codes, dates, numbers, phones.
 *
 * The artifact flags these per column by hand and sets them in mono; a live
 * result has no such flag, so the column is judged by what is actually in it.
 * Prose — an email, a name, a product title — stays in the body face.
 */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-/i;
const DATEISH = /^\d{4}-\d{2}(-\d{2})?([T ]\d{2}:\d{2}(:\d{2})?)?/;
const PHONE = /^\+?\d[\d\s().-]{5,}$/;
const CODE = /^[A-Z0-9]+(?:[-_][A-Z0-9]+)+$/;

function isCodeColumn(rows: Record<string, unknown>[], key: string): boolean {
  const seen = rows
    .map((row) => row[key])
    .filter((value) => value !== null && value !== undefined && value !== "");
  if (!seen.length) return false;
  return seen.every((value) => {
    if (typeof value === "number") return true;
    if (typeof value !== "string") return false;
    return (
      UUID.test(value) ||
      DATEISH.test(value) ||
      PHONE.test(value) ||
      CODE.test(value)
    );
  });
}

/** Keys the artifact greys out: the row's identity and its timestamps. */
function isMutedColumn(key: string): boolean {
  return key === "id" || key.endsWith("_id") || key.endsWith("_at");
}

export default function ResultTable({
  rows,
  columns,
  types,
  totalRows,
  query,
}: ResultTableProps) {
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 } | null>(null);
  const [page, setPage] = useState(0);

  // A new result set invalidates the page and the sort — leaving them would
  // show page 3 of a two-page answer, ordered by a column that no longer exists.
  useEffect(() => {
    setPage(0);
    setSort(null);
  }, [rows]);

  const numeric = useMemo(
    () =>
      Object.fromEntries(
        columns.map((key) => [
          key,
          NUMERIC_COLUMN_TYPE.test(types?.[key] ?? ""),
        ]),
      ),
    [columns, types],
  );

  const sorted = useMemo(() => {
    if (!sort) return rows;
    const { key, dir } = sort;
    return [...rows].sort((a, b) => {
      const left = a[key];
      const right = b[key];
      if (typeof left === "number" && typeof right === "number") {
        return (left - right) * dir;
      }
      // A column the service declared numeric sorts as numbers even when its
      // values arrive as strings — "10" before "9", not after it.
      if (numeric[key]) {
        const l = Number(display(left));
        const r = Number(display(right));
        if (Number.isFinite(l) && Number.isFinite(r)) return (l - r) * dir;
      }
      return (
        display(left).localeCompare(display(right), undefined, {
          numeric: true,
          sensitivity: "base",
        }) * dir
      );
    });
  }, [rows, sort, numeric]);

  const pages = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE));
  const current = Math.min(page, pages - 1);
  const slice = sorted.slice(
    current * PAGE_SIZE,
    current * PAGE_SIZE + PAGE_SIZE,
  );

  const code = useMemo(
    () =>
      Object.fromEntries(columns.map((key) => [key, isCodeColumn(rows, key)])),
    [columns, rows],
  );

  return (
    <>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse">
          <thead>
            <tr className="border-b border-n2s-line bg-n2s-card-2">
              {columns.map((key) => {
                const active = sort?.key === key;
                return (
                  <th
                    key={key}
                    scope="col"
                    className={`px-3.5 py-[9px] whitespace-nowrap ${
                      numeric[key] ? "text-right" : "text-left"
                    }`}
                    aria-sort={
                      active
                        ? sort.dir === 1
                          ? "ascending"
                          : "descending"
                        : "none"
                    }
                  >
                    <button
                      type="button"
                      onClick={() =>
                        setSort((currentSort) =>
                          currentSort?.key === key
                            ? { key, dir: currentSort.dir === 1 ? -1 : 1 }
                            : { key, dir: 1 },
                        )
                      }
                      className={`inline-flex cursor-pointer items-center gap-1.5 border-0 bg-transparent p-0 text-[10.5px] font-bold tracking-[0.07em] uppercase ${
                        active ? "text-n2s-pri-ink" : "text-n2s-ink-3"
                      }`}
                    >
                      {key}
                      {/* The declared type, where the service sent one: what
                         the column *is*, rather than what its sample of values
                         looks like. */}
                      {types?.[key] && (
                        <span className="font-mono text-[9px] font-normal tracking-normal text-n2s-ink-3 normal-case">
                          {types[key]}
                        </span>
                      )}
                      {/* The artifact keeps a ghosted arrow on every column, so
                          the header reads as sortable before it is clicked. */}
                      <span
                        aria-hidden="true"
                        className={`text-[9px] ${active ? "opacity-100" : "opacity-25"}`}
                      >
                        {active && sort.dir === -1 ? "▼" : "▲"}
                      </span>
                    </button>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {slice.map((row, index) => (
              <tr
                key={current * PAGE_SIZE + index}
                className="border-b border-n2s-line-2 hover:bg-n2s-card-2"
              >
                {columns.map((key) => (
                  <td
                    key={key}
                    className={`px-3.5 py-2.5 text-[12.5px] whitespace-nowrap ${
                      numeric[key] ? "text-right tabular-nums" : "text-left"
                    } ${code[key] || numeric[key] ? "font-mono" : ""} ${
                      isMutedColumn(key) ? "text-n2s-ink-3" : "text-n2s-ink-2"
                    }`}
                  >
                    {display(row[key])}
                  </td>
                ))}
              </tr>
            ))}
            {!slice.length && (
              <tr>
                <td
                  colSpan={Math.max(1, columns.length)}
                  className="px-3.5 py-6 text-center text-xs text-n2s-ink-3"
                >
                  No rows match “{query.trim()}”.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="flex items-center gap-2 border-t border-n2s-line bg-n2s-card-2 px-3 py-2">
        <span className="text-[11.5px] text-n2s-ink-3">
          {sorted.length
            ? `Showing ${current * PAGE_SIZE + 1}–${current * PAGE_SIZE + slice.length} of ${sorted.length.toLocaleString()}`
            : "No rows"}
          {sorted.length !== totalRows
            ? ` (filtered from ${totalRows.toLocaleString()})`
            : ""}
        </span>
        <div className="flex-1" />
        <button
          type="button"
          disabled={current === 0}
          onClick={() => setPage(current - 1)}
          className="cursor-pointer rounded-[7px] border border-n2s-line bg-n2s-card px-2.5 py-1 text-[11.5px] font-semibold text-n2s-ink-2 hover:bg-n2s-card-3 disabled:cursor-not-allowed disabled:opacity-40"
        >
          Previous
        </button>
        <button
          type="button"
          disabled={current >= pages - 1}
          onClick={() => setPage(current + 1)}
          className="cursor-pointer rounded-[7px] border border-n2s-line bg-n2s-card px-2.5 py-1 text-[11.5px] font-semibold text-n2s-ink-2 hover:bg-n2s-card-3 disabled:cursor-not-allowed disabled:opacity-40"
        >
          Next
        </button>
      </div>
    </>
  );
}
