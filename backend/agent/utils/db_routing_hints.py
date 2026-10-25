"""
Routing hints — compact, cached table/key-column facts per database (schema linking).

The db_router's single LLM call routes a question AND writes per-DB sub-queries + the join
key. Its only input used to be the human-written DB descriptions, so it had to GUESS table
and key-column names (observed failures: invented `owner_user_id`, sub-queries steered to
sparse/wrong tables). This module gives that call the real identifiers — the industry
"schema linking" practice — without inflating the prompt with full schemas.

NOTHING platform-specific is hardcoded: key candidates are DERIVED per agent —
a column qualifies as a cross-DB join-key candidate when its NAME EXISTS IN MORE THAN ONE of
the agent's routable databases (computed from information_schema) and it looks like an
identifier (generic shape check: *_id / *_key / *_code / *uuid* / email — a naming-convention
pattern, not a list of this platform's columns). A customer agent joining on product_id or
customer_id gets those detected exactly the same way.

Per-DB column maps are introspected live, cached in-process with a TTL, and fetched in
parallel with a hard overall timeout — routing never blocks on a slow or unreachable
database (it just proceeds without that DB's hints, i.e. the previous behaviour).
"""
from __future__ import annotations

import asyncio
import re
import time
from typing import Any, Dict, List

from logger import logger

# Generic identifier SHAPE (naming convention), not platform column names.
_IDENTIFIER_PATTERN = re.compile(r"(^|_)(id|key|code|uuid|email)$|uuid", re.IGNORECASE)

_TTL_SECONDS = 3600
_MAX_TABLES_LISTED = 30
_MAX_HINT_CHARS = 700
_FETCH_TIMEOUT_SECONDS = 6.0

# db_id -> ({table: [columns]}, monotonic_ts)
_cache: Dict[str, tuple] = {}


def _introspect_columns(db: Dict[str, Any]) -> Dict[str, List[str]]:
    """Blocking: read {table: [column, ...]} for one DB from information_schema."""
    import agent.db_utils.table_description_db_utils as tdu

    engine = (db.get("db_engine") or "").lower()
    schema_filter = "c.table_schema = DATABASE()" if engine == "mysql" else "c.table_schema = 'public'"

    conn = tdu.get_db_connection({"db_details": db})
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT c.table_name, c.column_name "
                "FROM information_schema.columns c "
                "JOIN information_schema.tables t "
                "  ON t.table_schema = c.table_schema AND t.table_name = c.table_name "
                f"WHERE {schema_filter} AND t.table_type = 'BASE TABLE' "
                "ORDER BY c.table_name, c.ordinal_position"
            )
            out: Dict[str, List[str]] = {}
            for t, c in cur.fetchall():
                out.setdefault(t, []).append(c)
            return out
    finally:
        try:
            conn.close()
        except Exception:
            pass


async def _columns_for(databases: List[Dict[str, Any]]) -> Dict[str, Dict[str, List[str]]]:
    """{db_id: {table: [columns]}} — cached per DB, parallel fetch, best-effort."""
    maps: Dict[str, Dict[str, List[str]]] = {}
    to_fetch: List[Dict[str, Any]] = []
    for db in databases:
        db_id = db.get("db_id") or ""
        hit = _cache.get(db_id)
        if hit and (time.monotonic() - hit[1]) < _TTL_SECONDS:
            maps[db_id] = hit[0]
        else:
            to_fetch.append(db)

    if to_fetch:
        async def _one(db: Dict[str, Any]) -> None:
            db_id = db.get("db_id") or ""
            try:
                cols = await asyncio.to_thread(_introspect_columns, db)
                _cache[db_id] = (cols, time.monotonic())
                maps[db_id] = cols
            except Exception as e:  # noqa: BLE001 — hints are best-effort, never block routing
                logger.warning("[routing_hints] introspection failed for %s: %s", db_id, str(e)[:120])
                maps[db_id] = {}

        try:
            await asyncio.wait_for(
                asyncio.gather(*(_one(db) for db in to_fetch)), timeout=_FETCH_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            logger.warning(
                "[routing_hints] fetch timed out after %.0fs; routing proceeds without %d hint(s)",
                _FETCH_TIMEOUT_SECONDS,
                sum(1 for d in to_fetch if (d.get("db_id") or "") not in maps),
            )
    return maps


async def get_routing_hints(databases: List[Dict[str, Any]]) -> Dict[str, str]:
    """{db_id: hint_str} for every DB.

    hint_str = "tables: a, b, … | shared keys: a(x_id, y_id), b(x_id)" where a "shared key"
    is an identifier-shaped column name present in AT LEAST TWO of this agent's databases —
    i.e. the columns a cross-DB join could actually use.
    """
    maps = await _columns_for(databases)

    # Column-name -> set of db_ids where it appears (identifier-shaped names only).
    name_dbs: Dict[str, set] = {}
    for db_id, tables in maps.items():
        names = {c for cols in tables.values() for c in cols if _IDENTIFIER_PATTERN.search(c)}
        for n in names:
            name_dbs.setdefault(n, set()).add(db_id)
    shared_names = {n for n, ids in name_dbs.items() if len(ids) >= 2}

    hints: Dict[str, str] = {}
    for db in databases:
        db_id = db.get("db_id") or ""
        tables = maps.get(db_id) or {}
        if not tables:
            hints[db_id] = ""
            continue
        table_names = list(tables)
        shown = table_names[:_MAX_TABLES_LISTED]
        parts = ["tables: " + ", ".join(shown) + (" …" if len(table_names) > len(shown) else "")]
        keyed = {
            t: [c for c in cols if c in shared_names]
            for t, cols in tables.items() if t in shown
        }
        keyed = {t: cols for t, cols in keyed.items() if cols}
        if keyed:
            parts.append(
                "shared keys: " + ", ".join(f"{t}({', '.join(cols)})" for t, cols in keyed.items())
            )
        hints[db_id] = " | ".join(parts)[:_MAX_HINT_CHARS]
    return hints
