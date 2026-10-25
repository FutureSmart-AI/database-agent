"""Store legacy integer table-visibility flags as the booleans the access policy reads

Revision ID: canonicalize_legacy_table_flags
Revises: add_owner_provider_key_source
Create Date: 2026-10-22 00:00:00.000000

WHY
---
`TableDescription.entry_flags` is the {table: included} map behind Settings → Tables &
visibility. Older writers stored it as integers (1 included, 0 excluded); current writers
store booleans (agent/utils/table_flag_writes.py). The table access policy
(agent/utils/table_access.py) deliberately accepts ONLY a nonempty map of booleans and
fails closed on anything else, so an agent whose flags are still integers has every
question denied as "could not be verified".

On the hosted service on 2026-10-22 every agent asked anything in the previous 30 days
stored integer flags (414 values: 412 x 1, 2 x 0), and none stored booleans.

WHAT THIS DOES
--------------
Rewrites, in place, only rows that are UNAMBIGUOUSLY convertible: a nonempty JSON object
with no duplicate keys whose every value is 1, 0, true or false. 1 -> true, 0 -> false;
the set of tables and each table's included/excluded meaning are unchanged.

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
Rows that are empty, not an object, contain duplicate keys or any other value are left as
they are. The policy treats a missing or malformed map as "not verified", and inventing
"every table is permitted" for them would be exactly the silent grant the policy exists to
prevent. Those agents keep failing closed until their owner reviews table visibility,
which writes a canonical map.

The reader is not relaxed: data is made canonical once, so strict reads stay strict.
"""

from alembic import op
import sqlalchemy as sa


revision = 'canonicalize_legacy_table_flags'
down_revision = 'add_owner_provider_key_source'
branch_labels = None
depends_on = None

_CONVERTIBLE = """
    entry_flags IS NOT NULL
    AND json_typeof(entry_flags) = 'object'
    AND entry_flags::jsonb <> '{}'::jsonb
    AND (SELECT count(*) FROM json_each(entry_flags))
        = (SELECT count(*) FROM jsonb_each(entry_flags::jsonb))
    AND NOT EXISTS (
        SELECT 1 FROM jsonb_each(entry_flags::jsonb) e
        WHERE e.value NOT IN ('1'::jsonb, '0'::jsonb, 'true'::jsonb, 'false'::jsonb))
    AND EXISTS (
        SELECT 1 FROM jsonb_each(entry_flags::jsonb) e
        WHERE e.value IN ('1'::jsonb, '0'::jsonb))
"""


def upgrade() -> None:
    # Idempotent: a converted row no longer has an integer value, so a re-run touches
    # nothing. updated_at is left alone — this is a storage-format change, not an edit
    # anyone made to the agent.
    # json_each keeps the stored key order.
    op.execute(sa.text(f"""
        UPDATE table_descriptions
        SET entry_flags = (
            SELECT json_object_agg(e.key, e.value::jsonb IN ('1'::jsonb, 'true'::jsonb))
            FROM json_each(entry_flags) e
        )
        WHERE {_CONVERTIBLE}
    """))


def downgrade() -> None:
    # Booleans are what every current writer produces and every reader accepts; there is
    # no reader that needs the integers back.
    pass
