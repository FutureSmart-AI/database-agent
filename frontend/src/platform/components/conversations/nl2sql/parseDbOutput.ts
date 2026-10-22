/**
 * Rows for a stored NL2SQL turn, whose result is kept as `db_output`.
 *
 * The live stream returns `debug_info.db_result` — `{ columns, rows, row_count }`
 * — and Result Data renders it directly. A thread read back from
 * `GET /nl2sql/api/v1/agents/{service_id}/sessions/{session_id}` carries the same
 * result as `db_output`, a JSON string of positional rows (`"[[59]]"`) with no
 * column names, so without this a reopened conversation showed the SQL and no
 * rows at all.
 *
 * Column names are recovered from the query's select list when it lines up
 * one-to-one with the values; anything else is labelled positionally rather than
 * guessed, since a wrong header is worse than an honest one.
 */

export interface DbResultLike {
  columns: Array<{ name: string }>;
  rows: Record<string, unknown>[];
  row_count: number;
}

/** Splits a select list on top-level commas, ignoring those inside `()`. */
function splitSelectList(selectList: string): string[] {
  const parts: string[] = [];
  let depth = 0;
  let current = "";
  for (const character of selectList) {
    if (character === "(") depth++;
    if (character === ")") depth--;
    if (character === "," && depth === 0) {
      parts.push(current);
      current = "";
      continue;
    }
    current += character;
  }
  if (current.trim()) parts.push(current);
  return parts.map((part) => part.trim()).filter(Boolean);
}

/**
 * The names a `SELECT` gives its columns: an explicit alias, or the column
 * itself when the expression is a plain (optionally qualified) column.
 */
export function columnNamesFromSql(sql: string | undefined): string[] {
  if (!sql) return [];
  const match = /select\s+([\s\S]+?)\s+from\s/i.exec(sql);
  if (!match) return [];

  return splitSelectList(match[1]).map((expression, index) => {
    const alias = /\s+as\s+"?([A-Za-z_][\w]*)"?$/i.exec(expression);
    if (alias) return alias[1];
    const plain = /^[A-Za-z_][\w]*\.?([A-Za-z_][\w]*)?$/.exec(
      expression.trim(),
    );
    if (plain) return (plain[1] ?? expression.trim()).replace(/^.*\./, "");
    return `column_${index + 1}`;
  });
}

/**
 * `"[[59]]"` → `{ columns: [{ name: "column_1" }], rows: [{ column_1: 59 }] }`.
 * Returns null for anything that is not positional rows, so a payload that
 * already carries `db_result` is left to it.
 */
export function parseDbOutput(
  dbOutput: unknown,
  sql?: string,
): DbResultLike | null {
  let parsed: unknown = dbOutput;
  if (typeof dbOutput === "string") {
    if (!dbOutput.trim()) return null;
    try {
      parsed = JSON.parse(dbOutput);
    } catch {
      return null;
    }
  }
  if (!Array.isArray(parsed) || parsed.length === 0) return null;
  if (!parsed.every((row) => Array.isArray(row))) return null;

  const positional = parsed as unknown[][];
  const width = Math.max(...positional.map((row) => row.length));
  const fromSql = columnNamesFromSql(sql);
  const names = Array.from({ length: width }, (_, index) =>
    fromSql.length === width ? fromSql[index] : `column_${index + 1}`,
  );

  return {
    columns: names.map((name) => ({ name })),
    rows: positional.map((row) =>
      Object.fromEntries(
        names.map((name, index) => [name, row[index] ?? null]),
      ),
    ),
    row_count: positional.length,
  };
}
