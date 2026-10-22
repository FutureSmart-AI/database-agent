export const ENGINES: Array<[value: string, label: string, port: number]> = [
  ["postgresql", "PostgreSQL", 5432],
  ["mysql", "MySQL", 3306],
  ["mssql", "SQL Server", 1433],
  ["sqlite", "SQLite", 0],
];
export const PROVISION_STEPS: Array<[title: string, detail: string]> = [
  [
    "Test the connection",
    "The credentials are checked before anything is saved",
  ],
  [
    "Create the agent",
    "The Database Agent service creates it and owns it from here",
  ],
  [
    "Connect the databases",
    "Each connection is stored and its schema read by the service",
  ],
];
export const SAMPLE_ROWS = `engine,host,port,database,user,password,description
postgresql,db1.acme.com,5432,orders_prod,analytics_ro,••••,"Live retail orders and products"
mysql,db2.acme.com,3306,warehouse,reader,••••,""`;
export const MONO_INPUT = "font-mono";

/**
 * `POST …/databases` answers as soon as the row is stored — the schema read it
 * kicks off lands a moment later, so its `table_count` is still 0 on a fresh
 * connection. `GET …/databases` reports the real number, so the new-agent
 * summary polls it on this ladder (ms between tries) until a count arrives.
 */
export const TABLE_COUNT_POLLS = [1200, 2500, 4000, 6000];
