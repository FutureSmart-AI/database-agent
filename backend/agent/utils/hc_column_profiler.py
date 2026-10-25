"""
Automatic column profiling and classification for the NL2SQL HC pipeline.

Classifies each column into one of:
  LOW_CARDINALITY_CATEGORICAL  — text/int with few distinct values (≤ threshold)
  HIGH_CARDINALITY_TEXT_SEARCH — text with many distinct values, needs vector search
  NORMAL_COLUMN                — numerics, dates, identifiers
  IGNORE                       — audit columns, near-empty columns, non-queryable types
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from logger import logger


def _to_json_safe(value: Any) -> Any:
    """Convert DB-returned values to JSON-serializable primitives."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return None
    return value


# ---------------------------------------------------------------------------
# Classification labels
# ---------------------------------------------------------------------------

LOW_CARDINALITY_CATEGORICAL = "LOW_CARDINALITY_CATEGORICAL"
HIGH_CARDINALITY_TEXT_SEARCH = "HIGH_CARDINALITY_TEXT_SEARCH"
NORMAL_COLUMN = "NORMAL_COLUMN"
IGNORE = "IGNORE"

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

_TEXT_TYPES = {
    "varchar", "char", "text", "tinytext", "mediumtext", "longtext",
    "character varying", "character", "bpchar", "name",
    "enum", "set",
}

_INT_TYPES = {
    "int", "tinyint", "smallint", "mediumint", "bigint", "integer",
    "int2", "int4", "int8", "serial", "bigserial", "smallserial",
}

_NON_QUERYABLE_TYPES = {
    "blob", "binary", "varbinary", "longblob", "mediumblob", "tinyblob",
    "bytea", "json", "jsonb", "array", "xml",
    "geometry", "point", "linestring", "polygon", "multipolygon",
    "multilinestring", "multipoint", "geometrycollection",
}

_DATETIME_TYPES = {
    "datetime", "timestamp", "timestamptz", "timestamp with time zone",
    "timestamp without time zone",
}

# Matches audit column names like created_at, updated_by, deleted_on, modified_at
_AUDIT_PATTERN = re.compile(
    r"(^|_)(created|updated|deleted|modified)(_at|_by|_on)?$",
    re.IGNORECASE,
)

# Detects UUID / hash-like varchar columns (e.g. varchar storing UUIDs)
_UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_HASH_PATTERN = re.compile(r"^[0-9a-f]{16,}$", re.IGNORECASE)


def _looks_like_identifier_column(sample_values: list) -> bool:
    """Return True if sample values look like UUIDs or hashes rather than human-readable text."""
    if not sample_values:
        return False
    checked = [v for v in sample_values[:10] if isinstance(v, str)]
    if not checked:
        return False
    matches = sum(
        1 for v in checked
        if _UUID_PATTERN.match(v) or _HASH_PATTERN.match(v)
    )
    return matches / len(checked) >= 0.8


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class ProfilingConfig:
    low_cardinality_threshold: int = field(
        default_factory=lambda: int(os.getenv("PROFILER_LOW_CARD_THRESHOLD", 20))
    )
    high_null_threshold: float = field(
        default_factory=lambda: float(os.getenv("PROFILER_HIGH_NULL_THRESHOLD", 95.0))
    )
    min_avg_text_len_for_hc: float = field(
        default_factory=lambda: float(os.getenv("PROFILER_MIN_AVG_TEXT_LEN", 2.0))
    )
    sample_limit: int = field(
        default_factory=lambda: int(os.getenv("PROFILER_SAMPLE_LIMIT", 5))
    )


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify_column(
    data_type: str,
    is_primary_key: bool,
    unique_values: int,
    row_count: int,
    null_percentage: float,
    average_text_length: Optional[float],
    config: ProfilingConfig,
    sample_values: Optional[List[Any]] = None,
    col_name: str = "",
) -> str:
    dt = data_type.lower().strip()

    # 1. IGNORE checks
    if null_percentage >= config.high_null_threshold:
        return IGNORE

    if dt in _NON_QUERYABLE_TYPES:
        return IGNORE

    # Integer primary key → auto-increment ID, not useful for filtering
    if is_primary_key and dt in _INT_TYPES:
        return IGNORE

    # Audit columns (created_at, updated_by, deleted_on, etc.)
    if col_name and _AUDIT_PATTERN.search(col_name):
        return IGNORE

    # 2. LOW_CARDINALITY_CATEGORICAL
    if row_count > 0 and 0 < unique_values <= config.low_cardinality_threshold:
        if dt in _TEXT_TYPES or dt in _INT_TYPES:
            return LOW_CARDINALITY_CATEGORICAL

    # 3. HIGH_CARDINALITY_TEXT_SEARCH
    # Exclude UUID/hash-like varchar columns (identifier columns, not human-readable text)
    if (
        unique_values > config.low_cardinality_threshold
        and dt in _TEXT_TYPES
        and (average_text_length is not None and average_text_length >= config.min_avg_text_len_for_hc)
        and not _looks_like_identifier_column(sample_values or [])
    ):
        return HIGH_CARDINALITY_TEXT_SEARCH

    # 4. NORMAL_COLUMN (default)
    return NORMAL_COLUMN


# ---------------------------------------------------------------------------
# Per-column profiling
# ---------------------------------------------------------------------------

def _quote_identifier(name: str, engine: str) -> str:
    """Wrap an identifier in the appropriate quoting character for the engine."""
    if engine == "postgresql":
        return f'"{name}"'
    return f"`{name}`"


def profile_column(
    cursor: Any,
    table_name: str,
    col_name: str,
    data_type: str,
    is_primary_key: bool,
    row_count: int,
    config: ProfilingConfig,
    engine: str = "mysql",
) -> dict:
    """Profile a single column and return its metrics + classification."""
    qt = _quote_identifier(table_name, engine)
    qc = _quote_identifier(col_name, engine)

    null_count = 0
    unique_values = 0
    average_text_length: Optional[float] = None
    sample_values: List[Any] = []

    try:
        # Null count
        cursor.execute(f"SELECT COUNT(*) FROM {qt} WHERE {qc} IS NULL")
        null_count = cursor.fetchone()[0] or 0

        null_percentage = (null_count / row_count * 100) if row_count > 0 else 0.0

        # Unique value count
        cursor.execute(f"SELECT COUNT(DISTINCT {qc}) FROM {qt}")
        unique_values = cursor.fetchone()[0] or 0

        cardinality_ratio = (unique_values / row_count) if row_count > 0 else 0.0

        dt = data_type.lower().strip()

        # Average text length (text columns only)
        if dt in _TEXT_TYPES:
            try:
                cursor.execute(
                    f"SELECT AVG(CHAR_LENGTH({qc})) FROM {qt} WHERE {qc} IS NOT NULL"
                )
                result = cursor.fetchone()[0]
                average_text_length = float(result) if result is not None else None
            except Exception:
                average_text_length = None

        # Sample values
        if unique_values <= config.low_cardinality_threshold:
            limit = config.low_cardinality_threshold + 1
        else:
            limit = config.sample_limit

        cursor.execute(f"SELECT DISTINCT {qc} FROM {qt} LIMIT {limit}")
        sample_values = [
            _to_json_safe(row[0])
            for row in cursor.fetchall()
            if row[0] is not None and _to_json_safe(row[0]) is not None
        ]

        classification = classify_column(
            data_type=data_type,
            is_primary_key=is_primary_key,
            unique_values=unique_values,
            row_count=row_count,
            null_percentage=null_percentage,
            average_text_length=average_text_length,
            config=config,
            sample_values=sample_values,
            col_name=col_name,
        )

        return {
            "data_type": data_type,
            "row_count": row_count,
            "unique_values": unique_values,
            "cardinality_ratio": round(cardinality_ratio, 6),
            "null_percentage": round(null_percentage, 2),
            "average_text_length": round(average_text_length, 2) if average_text_length is not None else None,
            "sample_values": sample_values,
            "classification": classification,
        }

    except Exception as e:
        logger.warning(f"[HC Profiler] Failed to profile {table_name}.{col_name}: {e}")
        return {
            "data_type": data_type,
            "row_count": row_count,
            "unique_values": 0,
            "cardinality_ratio": 0.0,
            "null_percentage": 0.0,
            "average_text_length": None,
            "sample_values": [],
            "classification": NORMAL_COLUMN,
        }


# ---------------------------------------------------------------------------
# Table-level profiling
# ---------------------------------------------------------------------------

def _get_columns_with_pk_info(cursor, table_name: str, db_name: str, engine: str) -> List[Tuple[str, str, bool]]:
    """Return list of (col_name, data_type, is_primary_key) for a table."""
    if engine == "mysql":
        cursor.execute(
            """
            SELECT COLUMN_NAME, DATA_TYPE,
                   CASE WHEN COLUMN_KEY = 'PRI' THEN 1 ELSE 0 END AS is_pk
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
            ORDER BY ORDINAL_POSITION
            """,
            (db_name, table_name),
        )
    else:  # postgresql
        cursor.execute(
            """
            SELECT c.column_name, c.data_type,
                   CASE WHEN pk.column_name IS NOT NULL THEN 1 ELSE 0 END AS is_pk
            FROM information_schema.columns c
            LEFT JOIN (
                SELECT ku.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage ku
                    ON tc.constraint_name = ku.constraint_name
                    AND tc.table_schema = ku.table_schema
                    AND tc.table_name = ku.table_name
                WHERE tc.constraint_type = 'PRIMARY KEY'
                  AND tc.table_schema = 'public'
                  AND tc.table_name = %s
            ) pk ON c.column_name = pk.column_name
            WHERE c.table_schema = 'public' AND c.table_name = %s
            ORDER BY c.ordinal_position
            """,
            (table_name, table_name),
        )
    return [(row[0], row[1], bool(row[2])) for row in cursor.fetchall()]


def _get_row_count(cursor, table_name: str, engine: str) -> int:
    qt = _quote_identifier(table_name, engine)
    try:
        cursor.execute(f"SELECT COUNT(*) FROM {qt}")
        result = cursor.fetchone()[0]
        return int(result) if result is not None else 0
    except Exception as e:
        logger.warning(f"[HC Profiler] Could not get row count for {table_name}: {e}")
        return 0


def profile_table(db_details: dict, table_name: str, config: ProfilingConfig) -> dict:
    """Profile all columns in a single table. Returns {col_name: profile_dict}."""
    engine = db_details.get("db_engine", "mysql")

    if engine == "mysql":
        import pymysql
        conn = pymysql.connect(
            host=db_details["db_host"],
            user=db_details["db_user"],
            password=db_details["db_password"],
            database=db_details["db_name"],
            port=int(db_details.get("db_port", 3306)),
        )
    elif engine == "postgresql":
        import psycopg2
        conn = psycopg2.connect(
            host=db_details["db_host"],
            user=db_details["db_user"],
            password=db_details["db_password"],
            database=db_details["db_name"],
            port=int(db_details.get("db_port", 5432)),
        )
    else:
        raise ValueError(f"Unsupported database engine: {engine}")

    profiles: dict = {}
    try:
        with conn.cursor() as cursor:
            columns = _get_columns_with_pk_info(
                cursor, table_name, db_details["db_name"], engine
            )
            row_count = _get_row_count(cursor, table_name, engine)

            for col_name, data_type, is_pk in columns:
                profiles[col_name] = profile_column(
                    cursor=cursor,
                    table_name=table_name,
                    col_name=col_name,
                    data_type=data_type,
                    is_primary_key=is_pk,
                    row_count=row_count,
                    config=config,
                    engine=engine,
                )
                logger.debug(
                    f"[HC Profiler] {table_name}.{col_name} → {profiles[col_name]['classification']}"
                )
    finally:
        conn.close()

    return profiles


def profile_all_tables(
    db_details: dict,
    config: ProfilingConfig,
    table_names: Optional[List[str]] = None,
) -> Dict[str, dict]:
    """Profile all (or specified) tables. Returns {table_name: {col_name: profile_dict}}."""
    if table_names is None:
        from knowledge.db_utils.database_db_utils import get_all_tables
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            table_names = loop.run_until_complete(get_all_tables(db_details))
        except RuntimeError:
            # No running event loop — create one
            table_names = asyncio.run(get_all_tables(db_details))

    results: Dict[str, dict] = {}
    start = time.time()
    for table in table_names:
        try:
            results[table] = profile_table(db_details, table, config)
            logger.info(
                f"[HC Profiler] Profiled table '{table}' — {len(results[table])} columns"
            )
        except Exception as e:
            logger.error(f"[HC Profiler] Failed to profile table '{table}': {e}")
            results[table] = {}

    logger.info(
        f"[HC Profiler] Completed profiling {len(results)} tables in {time.time() - start:.2f}s"
    )
    return results
