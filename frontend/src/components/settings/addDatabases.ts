import {
  addDatabase,
  generateDescription,
  type DbCredentials,
} from "@/data/databases";
import type { AgentDatabase } from "@/data/types";
import { apiMessage } from "@/lib/apiError";

export interface AddDatabasesResult {
  added: AgentDatabase[];
  /** One entry per connection the service refused, ready to show. */
  failed: Array<{ db_name: string; message: string }>;
  /** Databases added without a description, whose generation was started. */
  describing: string[];
}

/**
 * Adds several connections to one agent, one `POST …/databases` per row — the
 * route that tests the connection and reads the schema in the same call.
 *
 * Sequential on purpose: the service reads a whole schema per call, and a fan-out
 * of ten of those is what made the RDS path time out in the wizard's early
 * version. A row the service refuses is collected rather than thrown, so nine
 * good connections are not lost to one bad password.
 *
 * A row with no description gets one generated in the background, exactly as the
 * new-agent flow does — deliberately not awaited, since describing a large
 * schema takes minutes and the database is usable meanwhile.
 */
export async function addDatabases(
  serviceId: string,
  connections: DbCredentials[],
  onProgress?: (done: number, total: number) => void,
): Promise<AddDatabasesResult> {
  const added: AgentDatabase[] = [];
  const failed: AddDatabasesResult["failed"] = [];
  const describing: string[] = [];

  for (const [index, connection] of connections.entries()) {
    try {
      const database = await addDatabase(serviceId, connection);
      added.push(database);
      if (!database.description) {
        describing.push(database.db_name);
        void generateDescription(serviceId, database.db_id).catch(() => {
          // The database is connected either way; Settings → Configure →
          // Generate is where a failed description is retried.
        });
      }
    } catch (error) {
      failed.push({
        db_name: connection.db_name,
        message: apiMessage(error),
      });
    }
    onProgress?.(index + 1, connections.length);
  }

  return { added, failed, describing };
}

/** "orders_prod, warehouse and 2 more" — for the summary toast. */
export function nameList(names: string[]): string {
  if (names.length <= 3) return names.join(", ");
  return `${names.slice(0, 2).join(", ")} and ${names.length - 2} more`;
}
