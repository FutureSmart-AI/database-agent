import { buildApiUrl } from "@/platform/utils";
import axios from "@/platform/utils/axios";

import { APIS } from "./api";
import type {
  AgentDatabase,
  DescriptionSource,
  DescriptionStatus,
} from "./types";

/**
 * Databases, tables and few-shot examples — the NL2SQL service's multi-database
 * contract. Every route here is keyed by the agent's **service_id**
 * (`NL2SQL_XXXXXXXX`), not its chat `agent_id`.
 */

/** A database row exactly as the service returns it. */
interface WireDatabase {
  db_id: string;
  db_name: string;
  db_host: string;
  db_user: string;
  db_port: number;
  db_engine: string;
  description: string | null;
  description_status: DescriptionStatus;
  description_source: DescriptionSource;
  description_updated_at: string | null;
  is_active: boolean;
  status: "untested" | "connected" | "error";
  table_count: number | null;
  included_table_count?: number | null;
  /** Always masked as "***". */
  db_password: string;
}

export interface DbTable {
  table_name: string;
  description: string;
  is_included: boolean;
  column_count: number;
}

export interface FewShotExample {
  q: string;
  sql: string;
  src: "manual" | "correction";
}

/** Connection fields a database is created or edited with. */
export interface DbCredentials {
  db_name: string;
  db_engine: string;
  db_host: string;
  db_port: number;
  db_user: string;
  db_password?: string;
  description?: string;
}

function toDatabase(row: WireDatabase): AgentDatabase {
  return {
    db_id: row.db_id,
    db_name: row.db_name,
    db_engine: row.db_engine,
    db_host: row.db_host,
    db_port: row.db_port,
    db_user: row.db_user,
    active: row.is_active,
    reachable: row.status === "connected",
    latency: null,
    description: row.description,
    description_status: row.description_status,
    description_source: row.description_source,
    description_updated_at: row.description_updated_at
      ? Date.parse(row.description_updated_at)
      : null,
    table_count: row.table_count,
    // Tables the agent may read. Null when the service has no valid visibility
    // record for this database (the agent then reads none) or predates the field.
    included_table_count: row.included_table_count ?? null,
  };
}

/** `GET …/agents/{service_id}/databases`. */
export async function fetchDatabases(
  serviceId: string,
): Promise<AgentDatabase[]> {
  const url = buildApiUrl(APIS.DATABASES, { service_id: serviceId });
  const response = await axios.get<{ data: WireDatabase[] }>(url);
  return (response.data.data ?? []).map(toDatabase);
}

/** `POST …/databases` — add and test in one call. */
export async function addDatabase(
  serviceId: string,
  credentials: DbCredentials,
): Promise<AgentDatabase> {
  const url = buildApiUrl(APIS.DATABASES, { service_id: serviceId });
  const response = await axios.post<{ data: WireDatabase } & WireDatabase>(
    url,
    {
      db_name: credentials.db_name,
      db_engine: credentials.db_engine,
      db_host: credentials.db_host,
      db_port: credentials.db_port,
      db_user: credentials.db_user,
      db_password: credentials.db_password,
      ...(credentials.description
        ? { description: credentials.description }
        : {}),
    },
  );
  return toDatabase(response.data.data ?? response.data);
}

/** `PATCH …/databases/{db_id}` — partial update of the connection. */
export async function updateDatabase(
  serviceId: string,
  dbId: string,
  credentials: DbCredentials,
): Promise<AgentDatabase> {
  const url = buildApiUrl(APIS.DATABASE, {
    service_id: serviceId,
    db_id: dbId,
  });
  const response = await axios.patch<{ data: WireDatabase } & WireDatabase>(
    url,
    {
      db_name: credentials.db_name,
      db_engine: credentials.db_engine,
      db_host: credentials.db_host,
      db_port: credentials.db_port,
      db_user: credentials.db_user,
      ...(credentials.db_password
        ? { db_password: credentials.db_password }
        : {}),
    },
  );
  return toDatabase(response.data.data ?? response.data);
}

/** `DELETE …/databases/{db_id}`. */
export async function deleteDatabase(
  serviceId: string,
  dbId: string,
): Promise<void> {
  const url = buildApiUrl(APIS.DATABASE, {
    service_id: serviceId,
    db_id: dbId,
  });
  await axios.delete(url);
}

/** `PATCH …/databases/{db_id}/status` — include or exclude from answers. */
export async function setDatabaseActive(
  serviceId: string,
  dbId: string,
  isActive: boolean,
): Promise<void> {
  const url = buildApiUrl(APIS.DATABASE_STATUS, {
    service_id: serviceId,
    db_id: dbId,
  });
  await axios.patch(url, { is_active: isActive });
}

export interface DbCheckResult {
  db_id: string;
  db_name: string;
  connection: "connected" | "failed";
  response_ms: number;
  error: string | null;
}

/**
 * `POST …/databases/check` — tests every database and times each one.
 *
 * The rows come back under `databases`, alongside a `checked_at` stamp. Reading
 * only `data`/`results` meant this always resolved to an empty list, so a check
 * that reached every database reported "0 databases answered", threw away the
 * timings and made a per-row retry claim the database was still unreachable.
 */
export async function checkAllDatabases(
  serviceId: string,
): Promise<DbCheckResult[]> {
  const url = buildApiUrl(APIS.DATABASES_CHECK, { service_id: serviceId });
  const response = await axios.post<{
    databases?: DbCheckResult[];
    data?: DbCheckResult[];
    results?: DbCheckResult[];
  }>(url);
  const { databases, data, results } = response.data;
  return databases ?? data ?? results ?? [];
}

/** `POST /nl2sql/api/v1/databases/test` — tests credentials before saving. */
export async function testConnection(credentials: DbCredentials): Promise<{
  status: string;
  message: string;
}> {
  const response = await axios.post<{ status: string; message: string }>(
    APIS.DATABASE_TEST,
    {
      db_name: credentials.db_name,
      db_engine: credentials.db_engine,
      db_host: credentials.db_host,
      db_port: credentials.db_port,
      db_user: credentials.db_user,
      db_password: credentials.db_password,
    },
  );
  return response.data;
}

/** `PATCH …/databases/{db_id}/description` — save a hand-written description. */
export async function setDatabaseDescription(
  serviceId: string,
  dbId: string,
  description: string,
): Promise<void> {
  const url = buildApiUrl(APIS.DATABASE_DESCRIPTION, {
    service_id: serviceId,
    db_id: dbId,
  });
  await axios.patch(url, { description });
}

interface GenerateJob {
  job_id?: string;
  /** The service reports "running" then "done"; "failed" carries `error`. */
  status?: string;
  description?: string | null;
  error?: string | null;
}

/**
 * `POST …/description/generate`, then polls `…/description/generate/{job_id}`.
 *
 * The service reads a sample of the schema, so the work is asynchronous: the
 * first call returns a job id and the poll reports `completed` with the written
 * description. Rejects when the job fails or the deadline passes.
 */
export async function generateDescription(
  serviceId: string,
  dbId: string,
  { timeoutMs = 120_000, intervalMs = 2_000 } = {},
): Promise<string> {
  const startUrl = buildApiUrl(APIS.DATABASE_DESCRIPTION_GENERATE, {
    service_id: serviceId,
    db_id: dbId,
  });
  const started = await axios.post<GenerateJob>(startUrl);
  const jobId = started.data.job_id;
  if (!jobId) {
    if (started.data.description) return started.data.description;
    throw new Error("The service did not start a description job.");
  }

  const pollUrl = buildApiUrl(APIS.DATABASE_DESCRIPTION_POLL, {
    service_id: serviceId,
    db_id: dbId,
    job_id: jobId,
  });
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    // eslint-disable-next-line no-await-in-loop -- polling is sequential by nature
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
    // eslint-disable-next-line no-await-in-loop -- same
    const poll = await axios.get<GenerateJob>(pollUrl);
    // The service reports "done"; "completed" is accepted too so a wording
    // change on the backend does not hang this poll again.
    const status = poll.data.status;
    if (
      (status === "done" || status === "completed") &&
      poll.data.description
    ) {
      return poll.data.description;
    }
    if (status === "failed" || status === "error") {
      throw new Error(
        poll.data.error || "The service could not describe this database.",
      );
    }
  }
  throw new Error("Describing this database timed out.");
}

interface WireTable {
  table_name: string;
  description: string | null;
  is_included: boolean;
  column_count: number | null;
}

/** `GET …/databases/{db_id}/tables`. */
export async function fetchTables(
  serviceId: string,
  dbId: string,
): Promise<DbTable[]> {
  const url = buildApiUrl(APIS.TABLES, { service_id: serviceId, db_id: dbId });
  const response = await axios.get<{ data: WireTable[] }>(url);
  return (response.data.data ?? []).map((table) => ({
    table_name: table.table_name,
    description: table.description ?? "",
    is_included: table.is_included,
    column_count: table.column_count ?? 0,
  }));
}

/** A write to the table or few-shot endpoints answers with a message to show. */
export interface WriteResult {
  message?: string;
  /** Present when the rows were stored but the vector index was not updated. */
  vector_store_error?: string;
}

interface TableDescription {
  table_name: string;
  description: string;
}

/**
 * Saves table descriptions.
 *
 * The verb carries meaning here: `POST` creates the set for a database that has
 * none, and `PUT` merges into an existing set so tables missing from `tables`
 * keep the description they already had. Sending PUT to a database with no
 * descriptions saved nothing, which is why an upload to a fresh database looked
 * like it worked and changed nothing.
 */
export async function saveTables(
  serviceId: string,
  dbId: string,
  tables: TableDescription[],
  { merge }: { merge: boolean },
): Promise<WriteResult> {
  const url = buildApiUrl(APIS.TABLES, { service_id: serviceId, db_id: dbId });
  const body = {
    tables: tables.map((table) => ({
      table_name: table.table_name,
      description: table.description,
    })),
  };
  const response = merge
    ? await axios.put<WriteResult>(url, body)
    : await axios.post<WriteResult>(url, body);
  return response.data ?? {};
}

/**
 * `DELETE …/tables` — clears descriptions, by name or all of them. The tables
 * themselves stay listed; only the description text goes.
 */
export async function deleteTableDescriptions(
  serviceId: string,
  dbId: string,
  target: { table_names: string[] } | { delete_all: true },
): Promise<WriteResult & { deleted?: string[] }> {
  const url = buildApiUrl(APIS.TABLES, { service_id: serviceId, db_id: dbId });
  const response = await axios.delete<WriteResult & { deleted?: string[] }>(
    url,
    { data: target },
  );
  return response.data ?? {};
}

/** `POST …/tables/{table}/generate` — one table's description, synchronously. */
export async function generateTableDescription(
  serviceId: string,
  dbId: string,
  tableName: string,
): Promise<string> {
  const url = buildApiUrl(APIS.TABLE_GENERATE, {
    service_id: serviceId,
    db_id: dbId,
    table_name: tableName,
  });
  const response = await axios.post<{ description?: string }>(url);
  return response.data.description ?? "";
}

/** `PATCH …/tables/{table}/visibility` — include or exclude one table. */
export async function setTableVisibility(
  serviceId: string,
  dbId: string,
  tableName: string,
  isIncluded: boolean,
): Promise<void> {
  const url = buildApiUrl(APIS.TABLE_VISIBILITY, {
    service_id: serviceId,
    db_id: dbId,
    table_name: tableName,
  });
  await axios.patch(url, { is_included: isIncluded });
}

/**
 * `POST …/tables/generate`, polled like the description job.
 *
 * `overwrite: false` fills only the blank descriptions, so hand-written ones
 * survive; `true` rewrites every table.
 */
export async function generateTableDescriptions(
  serviceId: string,
  dbId: string,
  { overwrite = false, timeoutMs = 180_000, intervalMs = 3_000 } = {},
): Promise<DbTable[]> {
  const startUrl = buildApiUrl(APIS.TABLES_GENERATE, {
    service_id: serviceId,
    db_id: dbId,
  });
  const started = await axios.post<GenerateJob>(startUrl, null, {
    params: { overwrite },
  });
  const jobId = started.data.job_id;
  if (!jobId) throw new Error("The service did not start a table job.");

  const pollUrl = buildApiUrl(APIS.TABLES_GENERATE_POLL, {
    service_id: serviceId,
    db_id: dbId,
    job_id: jobId,
  });
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    // eslint-disable-next-line no-await-in-loop -- polling is sequential by nature
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
    // eslint-disable-next-line no-await-in-loop -- same
    const poll = await axios.get<GenerateJob>(pollUrl);
    if (poll.data.status === "done" || poll.data.status === "completed") {
      return fetchTables(serviceId, dbId);
    }
    if (poll.data.status === "failed" || poll.data.status === "error") {
      throw new Error(
        poll.data.error || "The service could not describe these tables.",
      );
    }
  }
  throw new Error("Describing these tables timed out.");
}

interface WireExample {
  natural_query?: string;
  question?: string;
  q?: string;
  sql_query?: string;
  sql?: string;
  source?: string;
}

/** `GET …/databases/{db_id}/few-shot-examples`. */
export async function fetchFewShot(
  serviceId: string,
  dbId: string,
): Promise<FewShotExample[]> {
  const url = buildApiUrl(APIS.FEW_SHOT, {
    service_id: serviceId,
    db_id: dbId,
  });
  const response = await axios.get<{ data: WireExample[] }>(url);
  return (response.data.data ?? []).map((row) => ({
    q: row.natural_query ?? row.question ?? row.q ?? "",
    sql: row.sql_query ?? row.sql ?? "",
    src: row.source === "correction" ? "correction" : "manual",
  }));
}

/**
 * The example shape the service accepts. The field is `natural_query` — sending
 * `question` was accepted as an empty row, so nothing was ever stored.
 */
const toWireExamples = (examples: FewShotExample[]) =>
  examples
    .filter((example) => example.q.trim() && example.sql.trim())
    .map((example) => ({
      natural_query: example.q.trim(),
      sql_query: example.sql.trim(),
    }));

/**
 * `POST …/few-shot-examples` — adds examples, merging with what is stored.
 *
 * This is the write the service supports for both adding and editing; PUT is a
 * whole-set replace that the deployed route does not implement, so saving used
 * to fail silently.
 */
export async function addFewShot(
  serviceId: string,
  dbId: string,
  examples: FewShotExample[],
): Promise<WriteResult> {
  const url = buildApiUrl(APIS.FEW_SHOT, {
    service_id: serviceId,
    db_id: dbId,
  });
  const response = await axios.post<WriteResult>(url, {
    examples: toWireExamples(examples),
  });
  return response.data ?? {};
}

/** `PUT …/few-shot-examples` — merges the given examples into the stored set. */
export async function saveFewShot(
  serviceId: string,
  dbId: string,
  examples: FewShotExample[],
): Promise<WriteResult> {
  const url = buildApiUrl(APIS.FEW_SHOT, {
    service_id: serviceId,
    db_id: dbId,
  });
  const response = await axios.put<WriteResult>(url, {
    examples: toWireExamples(examples),
  });
  return response.data ?? {};
}

/**
 * `DELETE …/few-shot-examples` — removes examples by their question text, or
 * every one of them. Questions are matched case- and space-insensitively.
 */
export async function deleteFewShot(
  serviceId: string,
  dbId: string,
  target: { nl_queries: string[] } | { delete_all: true },
): Promise<WriteResult & { deleted?: number }> {
  const url = buildApiUrl(APIS.FEW_SHOT, {
    service_id: serviceId,
    db_id: dbId,
  });
  const response = await axios.delete<WriteResult & { deleted?: number }>(url, {
    data: target,
  });
  return response.data ?? {};
}
