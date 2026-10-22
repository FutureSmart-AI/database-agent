/**
 * The tables an answer read that the agent is configured to exclude.
 *
 * Settings → Databases → Tables & visibility marks a table Excluded, and the
 * screen already reads those flags for the schema panel. Benchmark TC60 found
 * an answer that said "the requested data source is restricted or not
 * available" and drew the generated SQL and the excluded table's rows directly
 * underneath it. Whether the service should have run that query at all is its
 * own question; this is the screen refusing to display what came back.
 *
 * The comparison is on the bare table name: the trace reports whatever the SQL
 * said, so the same table arrives as `returns`, `public.returns` or
 * `public."Returns"`.
 */
const bareName = (table: string): string => {
  const last = table.split(".").pop() ?? table;
  return last
    .replace(/["'`\[\]]/g, "")
    .trim()
    .toLowerCase();
};

export function restrictedTablesInAnswer(
  tablesUsed: string[] | undefined,
  excludedTables: string[] | undefined,
): string[] {
  if (!tablesUsed?.length || !excludedTables?.length) return [];
  const excluded = new Set(excludedTables.map(bareName));
  const seen = new Set<string>();
  return tablesUsed.filter((table) => {
    const name = bareName(table);
    if (!excluded.has(name) || seen.has(name)) return false;
    seen.add(name);
    return true;
  });
}
