import { csvToRows } from "@/platform/components/conversations/nl2sql/csvToRows";

/**
 * Client-side parsing for the NL2SQL "import from file" flows (table
 * descriptions and few-shot examples).
 *
 * The backend file-upload endpoints are unreliable — CSV uploads 400 with
 * "No examples provided" and JSON uploads mis-map columns — so the frontend
 * parses the file itself and sends the structured array the backend accepts.
 * CSV is parsed with the shared RFC-4180 tokenizer (quote/newline aware, so
 * commas and line breaks inside SQL are preserved).
 */

export interface ParseResult<T> {
  rows: T[];
  /** File-level error (unparseable, wrong shape, no usable rows). */
  error?: string;
}

const looksJson = (text: string, fileName: string) =>
  fileName.toLowerCase().endsWith(".json") || /^[[{]/.test(text.trimStart());

/** CSV/JSON text → array of raw key→value records (keys lower-cased). */
const toRecords = (
  text: string,
  fileName: string,
): { records: Record<string, unknown>[]; error?: string } => {
  if (looksJson(text, fileName)) {
    let parsed: unknown;
    try {
      parsed = JSON.parse(text);
    } catch {
      return { records: [], error: "File is not valid JSON." };
    }
    if (!Array.isArray(parsed)) {
      return { records: [], error: "JSON must be an array of objects." };
    }
    return {
      records: parsed.map((item) =>
        item && typeof item === "object"
          ? (item as Record<string, unknown>)
          : {},
      ),
    };
  }
  return { records: csvToRows(text) };
};

/** Lower-case, trimmed key lookup that tolerates header whitespace/casing. */
const pick = (record: Record<string, unknown>, keys: string[]): string => {
  const normalized: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(record)) {
    normalized[k.trim().toLowerCase()] = v;
  }
  for (const key of keys) {
    const value = normalized[key];
    if (value != null && String(value).trim() !== "") {
      return String(value).trim();
    }
  }
  return "";
};

/** Parse a table-descriptions file into { table_name, description } rows. */
export const parseTableDescriptions = (
  text: string,
  fileName: string,
): ParseResult<{ table_name: string; description: string }> => {
  const { records, error } = toRecords(text, fileName);
  if (error) return { rows: [], error };

  const rows: { table_name: string; description: string }[] = [];
  for (const record of records) {
    const table_name = pick(record, ["table_name", "table", "name"]);
    if (!table_name) continue;
    rows.push({
      table_name,
      description: pick(record, ["description", "desc"]),
    });
  }
  if (rows.length === 0) {
    return {
      rows: [],
      error: "No valid { table_name, description } rows found in the file.",
    };
  }
  return { rows };
};

/** Parse a few-shot file into { natural_query, sql_query } rows. */
export const parseFewShotExamples = (
  text: string,
  fileName: string,
): ParseResult<{ natural_query: string; sql_query: string }> => {
  const { records, error } = toRecords(text, fileName);
  if (error) return { rows: [], error };

  const rows: { natural_query: string; sql_query: string }[] = [];
  for (const record of records) {
    const natural_query = pick(record, [
      "natural_query",
      "question",
      "nl_query",
    ]);
    const sql_query = pick(record, ["sql_query", "sql", "query"]);
    if (!natural_query || !sql_query) continue;
    rows.push({ natural_query, sql_query });
  }
  if (rows.length === 0) {
    return {
      rows: [],
      error: "No valid { natural_query, sql_query } rows found in the file.",
    };
  }
  return { rows };
};
