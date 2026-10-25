"""One way to open a connection to a user's source database.

Every caller passes the stored connection details; the port always comes from
them, falling back to the engine's default only when none was stored. Four helpers
used to build their own connections and dropped the port in six calls, so
a database on a non-default port (PostgreSQL on 5434) failed table listing,
column listing, description upload and the high-cardinality profiler with a
timeout against 5432 (DA-PROFILE-PORT-001).
"""
import psycopg2
import pymysql

DEFAULT_PORTS = {"mysql": 3306, "postgresql": 5432}


def source_port(db_details: dict) -> int:
    """The stored port, or the engine's default when none was stored."""
    port = db_details.get("db_port")
    if port in (None, ""):
        return DEFAULT_PORTS[db_details["db_engine"]]
    return int(port)


def open_source_connection(db_details: dict, **options):
    """Open a DB-API connection to the source database described by db_details."""
    engine = db_details.get("db_engine")
    if engine not in DEFAULT_PORTS:
        raise ValueError(f"Unsupported database engine: {engine}")
    common = dict(host=db_details["db_host"], user=db_details["db_user"],
                  password=db_details["db_password"], port=source_port(db_details))
    if engine == "mysql":
        return pymysql.connect(database=db_details["db_name"], **common, **options)
    return psycopg2.connect(dbname=db_details["db_name"], **common, **options)
