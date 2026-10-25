"""Which tables an agent may read, and whether a generated query stays inside them.

Table visibility is configured in the dashboard (Settings → Databases → Tables &
visibility) and stored as `TableDescription.entry_flags`, a {table: bool} map.

Until now that setting was enforced by asking the final_answer model to refuse if
the SQL "references any tables that are not in the explicitly allowed tables list"
(agent/utils/prompts.py). That is advice given after the fact, not a control: the
query was still generated, still executed, and its rows and SQL were still handed
to the caller alongside the refusal sentence. An excluded table could also be
reached indirectly — joined through to read a permitted table's rows — which the
refusal wording does not describe at all.

This module supplies the two facts a real check needs: the flags as configured,
and the tables a query actually touches.
"""

from __future__ import annotations

import json
import re
from typing import Dict, List, Optional, Set, Tuple

from logger import logger

# sqlglot understands dialect-specific quoting and syntax; sql_gen already targets
# one of these two engines.
_SQLGLOT_DIALECT = {
    "postgresql": "postgres",
    "postgres": "postgres",
    "mysql": "mysql",
}

# Schemas that are server metadata rather than customer data. A query reading one of
# these is not reading an excluded table, and blocking them would break introspection.
_METADATA_SCHEMAS = {"information_schema", "pg_catalog", "sys", "performance_schema"}


class TableAccessPolicyError(RuntimeError):
    """The product could not verify the required agent/database access policy."""


def deny_table_access(state, *, tables=None, policy_error=False):
    """A policy failure is terminal for this query, never a SQL-generation retry."""
    state.update(sql_query="", sql_error=None, db_result=[], db_columns=None,
                 graph_json=None, is_answered=False, access_denied_tables=tables or [],
                 access_policy_error=bool(policy_error))
    return state


async def get_table_visibility(
    user_id: Optional[str], agent_id: Optional[str], db_id: Optional[str]
) -> Tuple[List[str], List[str]]:
    """Return (permitted, excluded) table names for this agent and database.

    Unknown, missing or malformed policy is an explicit failure. A nonempty,
    identity-bound boolean map with every flag true is verified no-exclusions;
    an absent/empty map is not evidence that every table is permitted.
    """
    if not agent_id or not db_id:
        raise TableAccessPolicyError("Table access policy identity is missing")
    try:
        from agent.db_utils.table_description_db_utils import (
            list_table_description_from_db,
        )

        resp = await list_table_description_from_db(user_id, agent_id, db_id=db_id)
        record = (resp or {}).get("record")
        if (not isinstance(resp, dict) or resp.get("status") is not True or record is None
                or getattr(record, "chatbot_id", None) != agent_id
                or getattr(record, "db_id", None) != db_id):
            raise TableAccessPolicyError("Table access policy could not be verified")
        flags = getattr(record, "entry_flags", None)
        if isinstance(flags, str):
            def unique_pairs(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise TableAccessPolicyError("Duplicate table access flag")
                    result[key] = value
                return result
            flags = json.loads(flags, object_pairs_hook=unique_pairs)
        if (not isinstance(flags, dict) or not flags
                or any(type(t) is not str or not t.strip() or t != t.strip()
                       or type(on) is not bool for t, on in flags.items())
                or len({_bare(t) for t in flags}) != len(flags)):
            raise TableAccessPolicyError("Table access policy flags are invalid")
        permitted = [t for t, on in flags.items() if on]
        excluded = [t for t, on in flags.items() if not on]
        return permitted, excluded
    except TableAccessPolicyError:
        raise
    except Exception as e:
        logger.warning("[table_access] table visibility unavailable (%s)", type(e).__name__)
        raise TableAccessPolicyError("Table access policy is unavailable") from e


def _bare(name: str) -> str:
    """`public.orders` / `"Orders"` / `` `orders` `` -> orders."""
    return name.split(".")[-1].strip('`"[]').lower()


def blocked_table_names(names, permitted, excluded):
    """Apply the same verified map before schema samples or generated SQL reads."""
    if not permitted and not excluded:
        raise TableAccessPolicyError("Table access policy is empty")
    if any(type(t) is not str or not t.strip() for t in names):
        raise TableAccessPolicyError("Selected table identity is invalid")
    used = {_bare(t) for t in names}
    return sorted((used - {_bare(t) for t in permitted}) | (used & {_bare(t) for t in excluded})) or None


def tables_in_sql(sql: str, db_engine: Optional[str] = None) -> Optional[Set[str]]:
    """Bare, lower-cased names of every table the query reads.

    Returns None when the query could not be parsed — meaning "unknown", which is
    different from an empty set ("parsed fine, touches no table"). The caller
    decides what to do about not knowing.

    CTE names are excluded: `WITH recent AS (...) SELECT * FROM recent` reads
    whatever is inside the CTE, and `recent` itself is not a table in the database.
    """
    if not (sql or "").strip():
        return set()

    dialect = _SQLGLOT_DIALECT.get((db_engine or "").lower())
    try:
        import sqlglot
        from sqlglot import exp

        found: Set[str] = set()
        from sqlglot.optimizer.scope import Scope, traverse_scope
        # parse() rather than parse_one(): a semicolon-separated string is several
        # statements, and every one of them has to be checked.
        for statement in sqlglot.parse(sql, dialect=dialect):
            if statement is None:
                continue
            # Resolve each reference in its own scope. A CTE called returns
            # cannot hide public.returns or an outer physical returns reference.
            virtual_references = set()
            for scope in traverse_scope(statement):
                for reference, source in scope.selected_sources.values():
                    if isinstance(reference, exp.Table) and isinstance(source, Scope):
                        virtual_references.add(id(reference))
            for table in statement.find_all(exp.Table):
                if id(table) in virtual_references:
                    continue
                name = (table.name or "").strip()
                if not name:
                    return None
                schema = (table.db or "").strip().lower()
                if schema in _METADATA_SCHEMAS:
                    continue
                found.add(name.lower())
        return found
    except Exception as e:  # noqa: BLE001 — any parse/import failure means "unknown"
        logger.warning(
            "[table_access] could not parse SQL to determine tables read (%s): %s",
            type(e).__name__, str(e)[:200],
        )
        return None


# Fallback used only to name tables in a log line when parsing failed; never to
# decide access. Deliberately loose — it exists to make a blocked query debuggable.
_FROM_JOIN = re.compile(
    r"\b(?:FROM|JOIN|UPDATE|INTO)\s+([`\"\[]?[A-Za-z_][\w$]*[`\"\]]?(?:\s*\.\s*[`\"\[]?[A-Za-z_][\w$]*[`\"\]]?)?)",
    re.IGNORECASE,
)


def blocked_tables(
    sql: str,
    permitted: List[str],
    excluded: List[str],
    db_engine: Optional[str] = None,
) -> Optional[List[str]]:
    """Excluded tables this query would read, or None if it reads none.

    Only explicitly permitted physical tables may be read. Unknown new tables
    require a policy refresh. Unparseable SQL never establishes permission,
    including when the verified map contains no exclusions.
    """
    if not permitted and not excluded:
        raise TableAccessPolicyError("Table access policy is empty")

    excluded_bare = {_bare(t) for t in excluded}
    permitted_bare = {_bare(t) for t in permitted}

    used = tables_in_sql(sql, db_engine)
    if used is None:
        guessed = sorted({_bare(m) for m in _FROM_JOIN.findall(sql or "")} & excluded_bare)
        logger.warning(
            "[table_access] unparseable SQL with %d excluded table(s) configured — "
            "blocking. Regex guess of tables read: %s",
            len(excluded_bare), guessed or "none",
        )
        return sorted(excluded_bare) or ["<unverifiable table references>"]

    hits = used & excluded_bare
    # Absence from a verified map is not an operator grant.
    unknown = used - excluded_bare - permitted_bare
    if unknown:
        logger.info(
            "[table_access] query reads table(s) with no visibility flag, blocking: %s",
            sorted(unknown),
        )
    return sorted(hits | unknown) or None
