import type { DbCredentials } from "@/data/databases";

/**
 * Parses the connection rows the new-agent flow accepts when several databases
 * are added at once — CSV with a header row, or a JSON array.
 *
 * The CSV header names the fields, so column order does not matter, and the
 * common spellings are accepted (`database`/`db_name`, `password`/`db_password`).
 * A row missing a required field is reported rather than silently skipped: a
 * half-imported set is worse than a refused one.
 */

/** Header spellings mapped to the field they fill. */
const FIELDS: Record<string, keyof DbCredentials> = {
  engine: "db_engine",
  db_engine: "db_engine",
  host: "db_host",
  db_host: "db_host",
  port: "db_port",
  db_port: "db_port",
  database: "db_name",
  db: "db_name",
  db_name: "db_name",
  name: "db_name",
  user: "db_user",
  username: "db_user",
  db_user: "db_user",
  password: "db_password",
  db_password: "db_password",
  pass: "db_password",
  description: "description",
};

const DEFAULT_PORTS: Record<string, number> = {
  postgresql: 5432,
  mysql: 3306,
  mssql: 1433,
};

export interface ParseResult {
  connections: DbCredentials[];
  /** One line per row that could not be used, ready to show to the user. */
  errors: string[];
}

/** Splits one CSV line, honouring double quotes around a field. */
function splitCsvLine(line: string): string[] {
  const out: string[] = [];
  let field = "";
  let quoted = false;

  for (let index = 0; index < line.length; index++) {
    const char = line[index];
    if (quoted) {
      if (char === '"' && line[index + 1] === '"') {
        field += '"';
        index++;
      } else if (char === '"') {
        quoted = false;
      } else {
        field += char;
      }
    } else if (char === '"') {
      quoted = true;
    } else if (char === ",") {
      out.push(field.trim());
      field = "";
    } else {
      field += char;
    }
  }
  out.push(field.trim());
  return out;
}

function toConnection(
  row: Record<string, string>,
  rowNumber: number,
  errors: string[],
): DbCredentials | null {
  const engine = (row.db_engine || "postgresql").toLowerCase();
  const missing = (["db_name", "db_host", "db_user", "db_password"] as const)
    .filter((field) => !row[field])
    .map((field) => field.replace("db_", ""));

  if (missing.length) {
    errors.push(`Row ${rowNumber}: missing ${missing.join(", ")}.`);
    return null;
  }

  return {
    db_name: row.db_name,
    db_engine: engine,
    db_host: row.db_host,
    db_port: Number(row.db_port) || DEFAULT_PORTS[engine] || 5432,
    db_user: row.db_user,
    db_password: row.db_password,
    ...(row.description ? { description: row.description } : {}),
  };
}

/** Normalises one JSON object or CSV record onto the field names above. */
function normalise(record: Record<string, unknown>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(record)) {
    const field = FIELDS[key.trim().toLowerCase()];
    if (field && value != null) out[field] = String(value).trim();
  }
  return out;
}

export function parseConnections(input: string): ParseResult {
  const text = input.trim();
  const errors: string[] = [];
  if (!text) return { connections: [], errors: ["Nothing to import."] };

  // JSON first — an array of objects, or a single object.
  if (text.startsWith("[") || text.startsWith("{")) {
    try {
      const parsed = JSON.parse(text);
      const rows = Array.isArray(parsed) ? parsed : [parsed];
      const connections = rows
        .map((row, index) =>
          toConnection(
            normalise(row as Record<string, unknown>),
            index + 1,
            errors,
          ),
        )
        .filter((row): row is DbCredentials => row !== null);
      return { connections, errors };
    } catch {
      return { connections: [], errors: ["That is not valid JSON."] };
    }
  }

  // Otherwise CSV, whose first line names the columns.
  const lines = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  if (lines.length < 2) {
    return {
      connections: [],
      errors: ["Expected a header row and at least one connection."],
    };
  }

  const header = splitCsvLine(lines[0]).map((cell) => cell.toLowerCase());
  if (!header.some((cell) => FIELDS[cell])) {
    return {
      connections: [],
      errors: [
        "The first line must name the columns, e.g. engine,host,port,database,user,password.",
      ],
    };
  }

  const connections = lines
    .slice(1)
    .map((line, index) => {
      const cells = splitCsvLine(line);
      const record: Record<string, unknown> = {};
      header.forEach((key, column) => {
        record[key] = cells[column] ?? "";
      });
      return toConnection(normalise(record), index + 1, errors);
    })
    .filter((row): row is DbCredentials => row !== null);

  return { connections, errors };
}
