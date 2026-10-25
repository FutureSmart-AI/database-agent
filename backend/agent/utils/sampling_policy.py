"""Identity-bound pre-sampling policy from accepted S60; no SQL-execution changes.

Kept separately so the deployed model-only overlay need not include the other
S60 SQL parser/executor/route changes. Missing or malformed policy is a failure.
"""
from __future__ import annotations
import json
from typing import Optional, Tuple, List
from logger import logger

class TableAccessPolicyError(RuntimeError):
    """The product could not verify the required agent/database access policy."""


async def get_table_visibility(
    user_id: Optional[str], agent_id: Optional[str], db_id: Optional[str],
    *, legacy_integer_flags: bool = False
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
        # Only the deployed legacy overlay opts in; strict main/S60 callers do not.
        if legacy_integer_flags and isinstance(flags, dict):
            flags = {name: bool(value) if type(value) is int and value in (0, 1) else value
                     for name, value in flags.items()}
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
