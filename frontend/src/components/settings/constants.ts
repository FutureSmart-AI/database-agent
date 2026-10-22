import type { IconName } from "@/components/Icon";

export const TABS = [
  { key: "databases", label: "Databases" },
  { key: "answers", label: "Answers" },
  { key: "advanced", label: "Advanced" },
];
export const CONFIG_TABS = [
  { key: "description", label: "Description" },
  { key: "tables", label: "Tables & visibility" },
  { key: "examples", label: "Few-shot examples" },
];
export const ENGINES: Array<[value: string, label: string, port: number]> = [
  ["postgresql", "PostgreSQL", 5432],
  ["mysql", "MySQL", 3306],
  ["mssql", "SQL Server", 1433],
  ["sqlite", "SQLite", 0],
];

/** Header row and one example per engine — also what "Download template" saves. */
export const IMPORT_CSV_TEMPLATE = `engine,host,port,database,user,password,description
postgresql,db1.example.com,5432,sales,admin,secret,"E-commerce orders"
mysql,db2.example.com,3306,analytics,reader,pass,""`;

export const IMPORT_JSON_TEMPLATE = `[
  {
    "engine": "postgresql",
    "host": "db1.example.com",
    "port": 5432,
    "database": "sales",
    "user": "admin",
    "password": "secret",
    "description": "E-commerce orders"
  },
  {
    "engine": "mysql",
    "host": "db2.example.com",
    "port": 3306,
    "database": "analytics",
    "user": "reader",
    "password": "pass",
    "description": ""
  }
]`;

/** The three ways a database gets added, in the order they are offered. */
export type AddDbMode = "manual" | "import" | "rds";

export const ADD_DB_MODES: Array<
  [mode: AddDbMode, title: string, hint: string, glyph: IconName]
> = [
  [
    "manual",
    "Manual connection",
    "Enter host, credentials, database name",
    "db",
  ],
  [
    "import",
    "Import from CSV / JSON",
    "Bulk-add multiple databases from a file",
    "file",
  ],
  ["rds", "Connect from RDS", "Browse and select databases from RDS", "cloud"],
];

export type ImportTab = "csv" | "json" | "paste";

export const IMPORT_TABS: Array<{ key: ImportTab; label: string }> = [
  { key: "csv", label: "CSV file" },
  { key: "json", label: "JSON file" },
  { key: "paste", label: "Paste JSON" },
];

/** RDS answers on PostgreSQL and MySQL only. */
export const RDS_ENGINES = [
  { value: "postgresql", label: "PostgreSQL" },
  { value: "mysql", label: "MySQL" },
];
