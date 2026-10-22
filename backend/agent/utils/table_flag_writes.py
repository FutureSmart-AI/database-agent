"""Validate configuration display/write values; strict query readers stay strict.

Configuration display may normalize exact legacy0/1 in memory. Only an explicit
write persists normalization; there is no query-policy fallback or migration.
"""
import json


def canonical_table_flags_for_write(flags):
    if isinstance(flags, str):
        def unique(pairs):
            result = {}
            for name, value in pairs:
                if name in result:
                    raise ValueError("Duplicate table visibility flag")
                result[name] = value
            return result
        flags = json.loads(flags, object_pairs_hook=unique)
    if not isinstance(flags, dict):
        raise ValueError("Table visibility flags must be a map")
    canonical = {}
    for name, value in flags.items():
        if not isinstance(name, str) or not name.strip() or name != name.strip():
            raise ValueError("Invalid table visibility name")
        if type(value) is bool:
            canonical[name] = value
        elif type(value) is int and value in (0, 1):
            # Preserve the same meaning at the explicit configuration boundary.
            canonical[name] = value == 1
        else:
            raise ValueError("Table visibility flags must be booleans or exact legacy0/1")
    return canonical
