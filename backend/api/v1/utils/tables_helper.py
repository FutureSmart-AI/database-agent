import json
from agent.utils.table_flag_writes import canonical_table_flags_for_write
import asyncio
import traceback
from typing import List, Dict, Any, Optional
from fastapi import HTTPException, UploadFile
from chatbot_management.services.logger import logger
from knowledge.db_utils import table_description_db_utils, database_db_utils
from agent.db_utils.database_db_utils import get_primary_db_id
from knowledge.utils import common_utils
from chatbot_management.services.sqlmodel_session import get_async_session
from models.sql_models import ChatbotDetails
from sqlmodel import select


async def verify_agent_exists(agent_id: str):
    """Verify that an agent exists in the database"""
    async for session in get_async_session():
        result = await session.execute(select(ChatbotDetails).where(ChatbotDetails.agent_id == agent_id))
        agent = result.scalar_one_or_none()
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
        return agent


async def get_all_agent_table_descriptions(agent_id: str, db_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    List every table for a db_id — merged from the LIVE schema and stored metadata.

    On connect (before any description is saved) this still returns all real tables so the UI can
    show them immediately: each table comes back with its stored description (or "" if none) and
    its include/exclude flag (default included). Live-schema introspection is best-effort — if the
    DB is unreachable, it falls back to whatever descriptions are stored.
    """
    # Verify agent exists
    agent = await verify_agent_exists(agent_id)

    db_id = db_id or await get_primary_db_id(agent_id)

    # 1) Stored descriptions + include/exclude flags (may be empty on a freshly-connected DB).
    stored_desc: Dict[str, str] = {}
    entry_flags: Dict[str, Any] = {}
    db = await table_description_db_utils.list_table_description_from_db(None, agent_id, db_id=db_id)
    if db and db.get("status") and db.get("record"):
        record = db.get("record")
        description = record.description
        entry_flags = canonical_table_flags_for_write(record.entry_flags)
        if isinstance(description, str):
            try:
                description = json.loads(description)
            except Exception:
                description = []
        if isinstance(entry_flags, str):
            try:
                entry_flags = json.loads(entry_flags)
            except Exception:
                entry_flags = {}
        for item in (description or []):
            if isinstance(item, dict):
                for table_name, table_desc in item.items():
                    stored_desc[table_name] = table_desc

    # 2) Live table names from the actual database (best-effort — never fail the listing on this).
    #    Use the agent db utils (same path the runtime uses to connect); the knowledge-side
    #    get_db_connection does not resolve multi-DB db_ids.
    live_tables: List[str] = []
    introspected = False
    try:
        from agent.db_utils import database_db_utils as _agent_ddu
        from agent.db_utils import table_description_db_utils as _agent_tdu
        all_dbs = await _agent_ddu.get_all_databases(agent_id, active_only=False)
        target = next((d for d in (all_dbs or []) if d.get("db_id") == db_id), None)
        if target and target.get("db_engine"):
            # get_table_names_from_db is blocking (psycopg2/pymysql) → run off the event loop.
            live_tables = await asyncio.to_thread(
                _agent_tdu.get_table_names_from_db, {"db_details": target}
            ) or []
            introspected = True
    except Exception as e:
        logger.warning(f"[get_all_agent_table_descriptions] live table introspection failed for db {db_id}: {e}")
        live_tables = []

    # Refresh the cached count while a live answer is in hand, so the databases listing stays
    # accurate as tables are added or dropped. Only on a real introspection — an unreachable
    # database must not be cached as zero tables.
    if introspected and db_id:
        from api.v1.utils.databases_helper import cache_table_count
        await cache_table_count(db_id, len(live_tables))

    # 3) Merge — live schema is the source of truth for which tables exist; overlay stored
    #    descriptions/flags. Any stored-only table (e.g. removed from the DB) is still surfaced so
    #    nothing silently disappears.
    ordered = list(live_tables) + [t for t in stored_desc if t not in live_tables]

    response_data = []
    for table_name in ordered:
        response_data.append({
            "table_name": table_name,
            "description": stored_desc.get(table_name, ""),
            "is_included": bool(entry_flags.get(table_name, 1)),
            "column_count": 0,  # Placeholder
        })
    return response_data

def _normalize_table_descriptions(data: Any) -> List[Dict[str, str]]:
    """Normalize any accepted payload into a list of {table_name: description}.

    Accepts all shapes the UI / clients may send:
      * {"tables": [{"table_name": ..., "description": ...}]}   (wrapped form)
      * [{"table_name": ..., "description": ...}]               (bare array — what the UI sends)
      * {"descriptions": [{table: desc}]}
      * [{table: desc}]                                         (already normalized)
    """
    if isinstance(data, dict):
        if "tables" in data:
            return [{t["table_name"]: t["description"]} for t in data["tables"]]
        if "descriptions" in data:
            return data["descriptions"]
        raise HTTPException(status_code=400, detail="JSON object must contain 'tables' or 'descriptions'")
    if isinstance(data, list):
        # Bare array: either [{table_name, description}] (UI) or already [{table: desc}].
        if data and all(isinstance(e, dict) and "table_name" in e and "description" in e for e in data):
            return [{e["table_name"]: e["description"]} for e in data]
        return data
    raise HTTPException(status_code=400, detail="Unrecognized table_descriptions format")


async def create_agent_table_descriptions(
    agent_id: str,
    content_type: str,
    raw_body: bytes = None,
    file: Optional[UploadFile] = None,
    table_descriptions_form: Optional[str] = None,
    db_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Upload/Create table descriptions for an agent (bulk)
    """
    # Verify agent exists
    agent = await verify_agent_exists(agent_id)

    db_id = db_id or await get_primary_db_id(agent_id)

    file_name = ""
    description = []

    try:
        # Priority 1: JSON body
        if content_type.startswith("application/json"):
            if raw_body:
                description = _normalize_table_descriptions(json.loads(raw_body.decode()))
        # Priority 2: File upload
        elif file and file.filename:
            if table_descriptions_form and table_descriptions_form not in [None, "", "string"]:
                raise HTTPException(status_code=400, detail="Provide either 'file' or 'table_descriptions', not both")

            if file.filename.endswith('.json'):
                contents = await file.read()
                description = _normalize_table_descriptions(json.loads(contents.decode('utf-8')))
                file_name = file.filename
            else:
                description, file_name = await common_utils.extract_from_csv(file, mode="table_description")
        # Priority 3: Form field JSON string
        elif table_descriptions_form and table_descriptions_form not in [None, "", "string"]:
            description = _normalize_table_descriptions(json.loads(table_descriptions_form))
        else:
            raise HTTPException(status_code=400, detail="Provide tables via JSON body, file upload, or table_descriptions field")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error loading data: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Error loading data: {str(e)}")

    if not description:
        raise HTTPException(status_code=400, detail="No table descriptions provided")

    # Get database tables (scoped to the target db_id, not the agent's primary DB)
    db_details = await database_db_utils.get_db_connection(None, agent_id, db_id=db_id)
    tables = []
    if db_details.get("status") and db_details.get("db_details"):
        tables = await database_db_utils.get_all_tables(db_details["db_details"])

    # Build description mapping
    description_final = []
    description_map = {list(entry.keys())[0]: entry for entry in description}
    previous = await table_description_db_utils.list_table_description_from_db(None, agent_id, db_id=db_id)
    if not isinstance(previous, dict) or "record" not in previous:
        raise HTTPException(status_code=500, detail="Existing table visibility could not be verified")
    record = previous.get("record")
    if record and (record.chatbot_id != agent_id or record.db_id != db_id):
        raise HTTPException(status_code=500, detail="Existing table visibility identity is invalid")
    previous_flags = canonical_table_flags_for_write(record.entry_flags) if record else {}

    if tables:
        for table in tables:
            if table in description_map:
                description_final.append(description_map[table])
            else:
                description_final.append({table: ""})
        entry_flags = {table: previous_flags.get(table, True) for table in tables}
    else:
        description_final = description
        entry_flags = {list(entry.keys())[0]: previous_flags.get(list(entry.keys())[0], True) for entry in description}

    db_res = await table_description_db_utils.upload_to_db_table_description(
        user_id, agent_id, file_name, "", description_final, entry_flags, db_id=db_id
    )

    if db_res and db_res.get("status"):
        table_not_found = []
        if tables:
            for table in description_map.keys():
                if table not in tables:
                    table_not_found.append(table)
        
        count = len(description_map)
        noun = "description" if count == 1 else "descriptions"
        message = f"Table {noun} uploaded successfully."
        if table_not_found:
            tbl = "Table" if len(table_not_found) == 1 else "Tables"
            message += f" Note: {tbl} {table_not_found} not found in database."

        return {
            "status": "success",
            "tables_added": count,
            "message": message
        }

    raise HTTPException(status_code=500, detail=f"Table descriptions failed to upload. Database response: {db_res}")

async def update_agent_table_descriptions(
    agent_id: str,
    content_type: str,
    raw_body: bytes = None,
    file: Optional[UploadFile] = None,
    table_descriptions_form: Optional[str] = None,
    db_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Update table descriptions for an agent (bulk)
    """
    # Verify agent exists
    agent = await verify_agent_exists(agent_id)

    db_id = db_id or await get_primary_db_id(agent_id)

    file_name = ""
    update_request = []

    try:
        # Priority 1: JSON body — accepts a bare [{table_name, description}] array (what the UI
        # sends), a {"tables": [...]} object, {"descriptions": [...]}, or already-normalized data.
        if content_type.startswith("application/json"):
            if raw_body:
                update_request = _normalize_table_descriptions(json.loads(raw_body.decode()))
        # Priority 2: File upload
        elif file and file.filename:
            if table_descriptions_form and table_descriptions_form not in [None, "", "string"]:
                raise HTTPException(status_code=400, detail="Provide either 'file' or 'table_descriptions', not both")

            if file.filename.endswith('.json'):
                contents = await file.read()
                update_request = _normalize_table_descriptions(json.loads(contents.decode('utf-8')))
                file_name = file.filename
            else:
                descriptions_list, file_name = await common_utils.extract_from_csv(file, mode="table_description")
                for item in descriptions_list:
                    if isinstance(item, dict):
                        for table_name, desc in item.items():
                            if table_name:
                                update_request.append({table_name: desc})
        # Priority 3: Form field JSON string
        elif table_descriptions_form and table_descriptions_form not in [None, "", "string"]:
            update_request = _normalize_table_descriptions(json.loads(table_descriptions_form))
        else:
            raise HTTPException(status_code=400, detail="Provide tables via JSON body, file upload, or table_descriptions field")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error loading data: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Error loading data: {str(e)}")

    if not update_request:
        raise HTTPException(status_code=400, detail="No table descriptions provided")

    # Get existing descriptions
    db = await table_description_db_utils.list_table_description_from_db(None, agent_id, db_id=db_id)
    db_dict = {}
    if db and db.get("record") and db.get("record").description:
        existing_desc = db.get("record").description
        if isinstance(existing_desc, str):
            existing_desc = json.loads(existing_desc)
        if isinstance(existing_desc, list):
            for item in existing_desc:
                if isinstance(item, dict):
                    db_dict.update(item)

    # Get database tables (scoped to the target db_id, not the agent's primary DB)
    db_details = await database_db_utils.get_db_connection(None, agent_id, db_id=db_id)
    if not (db_details and db_details.get("status") and db_details.get("db_details")):
        raise HTTPException(status_code=400, detail="No database connection found for this agent")
    
    tables = await database_db_utils.get_all_tables(db_details["db_details"])

    # Process updates
    table_not_found = []
    for update in update_request:
        if isinstance(update, dict):
            for key, value in update.items():
                if key in tables:
                    db_dict[key] = value
                else:
                    table_not_found.append(key)
        else:
            raise HTTPException(status_code=400, detail="Invalid update format")

    final_db_records = [{k: v} for k, v in db_dict.items()]
    db_res = await table_description_db_utils.update_table_description(
        user_id, agent_id, file_name, description=final_db_records, db_id=db_id
    )

    if db_res and db_res.get("status"):
        updated_count = len(update_request) - len(table_not_found)
        noun = "description" if updated_count == 1 else "descriptions"
        message = f"Table {noun} updated successfully."
        if table_not_found:
            tbl = "Table" if len(table_not_found) == 1 else "Tables"
            message += f" Note: {tbl} {table_not_found} not found in database."
        return {"status": "success", "message": message}

    raise HTTPException(status_code=500, detail="Table descriptions failed to be updated")

async def delete_agent_table_descriptions(
    agent_id: str,
    table_names: Optional[List[str]] = None,
    db_id: Optional[str] = None,
    delete_all: bool = False,
    user_id: Optional[str] = None,
) -> List[str]:
    """
    Clear table descriptions for an agent — either the named tables, or ALL of them when
    `delete_all=True`. Tables are NOT removed; only their description text is cleared (each
    cleared table stays listed with an empty description). Returns the list of tables cleared.

    user_id: acting dashboard user, recorded as deleted_by on the surviving row; NULL for
    internal / API-key (master) callers.
    """
    # Verify agent exists
    agent = await verify_agent_exists(agent_id)

    db_id = db_id or await get_primary_db_id(agent_id)

    if not delete_all and not table_names:
        raise HTTPException(status_code=400, detail="Provide table_names or delete_all")

    db = await table_description_db_utils.list_table_description_from_db(None, agent_id, db_id=db_id)
    if db and db.get("status") and db.get("record"):
        record = db.get("record")
        description = record.description
        if isinstance(description, str):
            try:
                description = json.loads(description)
            except:
                description = []

        existing_table_names = []
        for desc in description:
            if isinstance(desc, dict):
                existing_table_names.extend(desc.keys())

        if delete_all:
            targets = list(existing_table_names)
        else:
            for table_name in table_names:
                if table_name not in existing_table_names:
                    raise HTTPException(status_code=404, detail=f"Table {table_name} not present in the existing table descriptions")
            targets = list(table_names)

        for d in description:
            for key in targets:
                d.pop(key, None)

        for key in targets:
            description.append({key: ""})

        cleaned_data = [d for d in description if d]
        db_res = await table_description_db_utils.delete_table_descriptions_db(user_id, agent_id, cleaned_data, db_id=db_id)

        if db_res and db_res.get("status"):
            return targets

    raise HTTPException(status_code=500, detail="Table descriptions failed to be deleted")

async def get_agent_high_cardinality_columns(agent_id: str, user_id: str = None, db_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Get high cardinality columns for an agent
    """
    db_id = db_id or await get_primary_db_id(agent_id)
    result = await table_description_db_utils.get_high_cardinality_columns(user_id, agent_id, db_id=db_id)
    if result and result.get("status") and result.get("record"):
        record = result.get("record")
        high_cardinality_columns_value = getattr(record, 'high_cardinality_columns', record)
        if isinstance(record, (tuple, list)) and len(record) > 0:
            high_cardinality_columns_value = record[0]

        if isinstance(high_cardinality_columns_value, str) and high_cardinality_columns_value:
            try:
                high_cardinality_data = json.loads(high_cardinality_columns_value)
            except:
                high_cardinality_data = {}
        elif high_cardinality_columns_value is None:
            high_cardinality_data = {}
        else:
            high_cardinality_data = high_cardinality_columns_value

        response_data = []
        if isinstance(high_cardinality_data, dict):
            for table_name, columns in high_cardinality_data.items():
                if isinstance(columns, list):
                    for column_name in columns:
                        response_data.append({"table_name": table_name, "column_name": column_name})
        elif isinstance(high_cardinality_data, list):
            response_data = high_cardinality_data
        return response_data
    return []

async def set_agent_high_cardinality_columns(agent_id: str, user_id: str, columns_data: List[Dict[str, str]], db_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Set high cardinality columns for an agent
    """
    if not columns_data:
        raise HTTPException(status_code=400, detail="No valid high cardinality columns provided")

    db_id = db_id or await get_primary_db_id(agent_id)
    db = await table_description_db_utils.get_high_cardinality_columns(user_id, agent_id, db_id=db_id)
    record = db.get("record", None)
    existing_hc = {}
    if record is not None:
        val = getattr(record, 'high_cardinality_columns', record)
        if isinstance(record, (tuple, list)) and len(record) > 0:
            val = record[0]
        if isinstance(val, str) and val:
            existing_hc = json.loads(val)
        elif val is not None:
            existing_hc = val

    table_columns_map = {}
    for col in columns_data:
        table_name = col["table_name"]
        column_name = col["column_name"]
        if table_name not in table_columns_map:
            table_columns_map[table_name] = []
        table_columns_map[table_name].append(column_name)

    for table_name, column_names in table_columns_map.items():
        existing_hc[table_name] = column_names

    result = await table_description_db_utils.upload_high_cardinality_columns(user_id, agent_id, existing_hc, db_id=db_id)
    if result and result.get("status"):
        return {"status": "success", "columns_configured": len(columns_data), "message": "High cardinality columns configured"}
    raise HTTPException(status_code=500, detail="Failed to configure high cardinality columns")

async def delete_agent_high_cardinality_columns(agent_id: str, user_id: str, columns_to_remove: List[Dict[str, str]], db_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Delete specific high cardinality columns for an agent
    """
    if not columns_to_remove:
        raise HTTPException(status_code=400, detail="No columns specified for removal")

    db_id = db_id or await get_primary_db_id(agent_id)
    db = await table_description_db_utils.get_high_cardinality_columns(user_id, agent_id, db_id=db_id)
    record = db.get("record", None)
    existing_hc = {}
    if record is not None:
        val = getattr(record, 'high_cardinality_columns', record)
        if isinstance(record, (tuple, list)) and len(record) > 0:
            val = record[0]
        if isinstance(val, str) and val:
            existing_hc = json.loads(val)
        elif val is not None:
            existing_hc = val

    if not existing_hc:
        raise HTTPException(status_code=404, detail="No high cardinality columns configured for this agent")

    removed_count = 0
    for col in columns_to_remove:
        t, c = col["table_name"], col["column_name"]
        if t in existing_hc and isinstance(existing_hc[t], list) and c in existing_hc[t]:
            existing_hc[t].remove(c)
            removed_count += 1
            if not existing_hc[t]:
                del existing_hc[t]

    if removed_count == 0:
        raise HTTPException(status_code=404, detail="None of the specified columns were found in the configuration")

    result = await table_description_db_utils.upload_high_cardinality_columns(user_id, agent_id, existing_hc, db_id=db_id)
    if result and result.get("status"):
        return {"status": "success", "columns_removed": removed_count, "message": "High cardinality columns removed"}
    raise HTTPException(status_code=500, detail="Failed to remove high cardinality columns")

async def get_specific_agent_table_description(agent_id: str, table_name: str, db_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Get specific table description
    """
    # Verify agent exists
    agent = await verify_agent_exists(agent_id)

    db_id = db_id or await get_primary_db_id(agent_id)
    db = await table_description_db_utils.list_table_description_from_db(None, agent_id, db_id=db_id)
    if db and db.get("status") and db.get("record"):
        record = db.get("record")
        description = record.description
        entry_flags = record.entry_flags or {}
        if isinstance(description, str):
            try:
                description = json.loads(description)
            except:
                description = []
        if isinstance(entry_flags, str):
            try:
                entry_flags = json.loads(entry_flags)
            except:
                entry_flags = {}

        for item in description:
            if isinstance(item, dict) and table_name in item:
                return {
                    "table_name": table_name,
                    "description": item[table_name],
                    "is_included": bool(entry_flags.get(table_name, 1)),
                    "columns": []
                }
        raise HTTPException(status_code=404, detail=f"Table {table_name} not found")
    raise HTTPException(status_code=404, detail=f"No table descriptions found for agent {agent_id}")

async def update_specific_agent_table_description(agent_id: str, table_name: str, body: Any, db_id: Optional[str] = None, user_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Update specific table description
    """
    # Verify agent exists
    agent = await verify_agent_exists(agent_id)

    db_id = db_id or await get_primary_db_id(agent_id)
    db = await table_description_db_utils.list_table_description_from_db(None, agent_id, db_id=db_id)
    if not (db and db.get("status") and db.get("record")):
        raise HTTPException(status_code=404, detail=f"No table descriptions found for agent {agent_id}")

    record = db.get("record")
    description = record.description
    entry_flags = record.entry_flags or {}
    if isinstance(description, str):
        try:
            description = json.loads(description)
        except:
            description = []
    if isinstance(entry_flags, str):
        try:
            entry_flags = json.loads(entry_flags)
        except:
            entry_flags = {}

    table_found = False
    for item in description:
        if isinstance(item, dict) and table_name in item:
            item[table_name] = body.description
            table_found = True
            break
    if not table_found:
        description.append({table_name: body.description})

    if body.is_included is not None:
        entry_flags[table_name] = body.is_included

    db_res = await table_description_db_utils.upload_to_db_table_description(
        user_id, agent_id, record.file_name or "", record.url or "", description, entry_flags, db_id=db_id
    )
    if db_res and db_res.get("status"):
        return {"status": "success", "message": "Table description updated successfully."}
    raise HTTPException(status_code=500, detail="Failed to update table description")

async def update_agent_table_visibility(agent_id: str, table_name: str, is_included: bool, db_id: Optional[str] = None, user_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Include/Exclude a specific table
    """
    # Verify agent exists
    agent = await verify_agent_exists(agent_id)
    db_id = db_id or await get_primary_db_id(agent_id)

    # Get existing entry_flags
    db = await table_description_db_utils.list_table_description_from_db(None, agent_id, db_id=db_id)

    if not (db and db.get("status") and db.get("record")):
        raise HTTPException(status_code=404, detail=f"No table descriptions found for agent {agent_id}")

    record = db.get("record")
    entry_flags = record.entry_flags or {}

    # Parse entry_flags if it's a string
    if isinstance(entry_flags, str):
        try:
            entry_flags = json.loads(entry_flags)
        except:
            entry_flags = {}

    # Update the visibility flag
    entry_flags[table_name] = is_included

    # Update database
    db_result = await table_description_db_utils.upload_to_db_include_or_exclude_table_names(
        user_id, agent_id, entry_flags, db_id=db_id
    )

    if db_result and db_result.get("status"):
        return {
            "status": "success",
            "table_name": table_name,
            "is_included": is_included,
            "message": "Table visibility updated"
        }

    raise HTTPException(status_code=500, detail="Failed to update table visibility")

async def update_agent_bulk_table_visibility(agent_id: str, tables_visibility: List[Any], db_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Bulk include/exclude tables
    """
    # Verify agent exists
    agent = await verify_agent_exists(agent_id)
    db_id = db_id or await get_primary_db_id(agent_id)

    # Get existing entry_flags
    db = await table_description_db_utils.list_table_description_from_db(None, agent_id, db_id=db_id)

    if not (db and db.get("status") and db.get("record")):
        raise HTTPException(status_code=404, detail=f"No table descriptions found for agent {agent_id}")

    record = db.get("record")
    entry_flags = record.entry_flags or {}

    # Parse entry_flags if it's a string
    if isinstance(entry_flags, str):
        try:
            entry_flags = json.loads(entry_flags)
        except:
            entry_flags = {}

    # Update the visibility flags
    for table_item in tables_visibility:
        entry_flags[table_item.table_name] = table_item.is_included

    # Update database
    db_result = await table_description_db_utils.upload_to_db_include_or_exclude_table_names(
        None, agent_id, entry_flags, db_id=db_id
    )

    if db_result and db_result.get("status"):
        return {
            "status": "success",
            "updated_count": len(tables_visibility),
            "message": "Table visibility updated"
        }

    raise HTTPException(status_code=500, detail="Failed to update table visibility")

