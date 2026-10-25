import json
import traceback
from typing import List, Dict, Any, Optional
from fastapi import HTTPException, UploadFile
from logger import logger
from knowledge.db_utils import table_description_db_utils, database_db_utils
from knowledge.utils import common_utils
from chatbot_management.db_utils.chatbot_params_db_utils import get_chatbot_details_by_agent_id

async def get_all_agent_table_descriptions(agent_id: str) -> List[Dict[str, Any]]:
    """
    Get all table descriptions for an agent
    """
    # Verify agent exists
    agent = await get_chatbot_details_by_agent_id(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    # Get table descriptions
    db = await table_description_db_utils.list_table_description_from_db(None, agent_id)
    
    if db and db.get("status") and db.get("record"):
        record = db.get("record")
        description = record.description
        entry_flags = record.entry_flags or {}
        
        # Parse description if it's a string
        if isinstance(description, str):
            try:
                description = json.loads(description)
            except:
                description = []
        
        # Parse entry_flags if it's a string
        if isinstance(entry_flags, str):
            try:
                entry_flags = json.loads(entry_flags)
            except:
                entry_flags = {}
        
        # Convert to response format
        response_data = []
        for item in description:
            if isinstance(item, dict):
                for table_name, table_desc in item.items():
                    response_data.append({
                        "table_name": table_name,
                        "description": table_desc,
                        "is_included": bool(entry_flags.get(table_name, 1)),
                        "column_count": 0  # Placeholder
                    })
        
        return response_data
    
    return []

async def create_agent_table_descriptions(
    agent_id: str, 
    content_type: str, 
    raw_body: bytes = None, 
    file: Optional[UploadFile] = None, 
    table_descriptions_form: Optional[str] = None
) -> Dict[str, Any]:
    """
    Upload/Create table descriptions for an agent (bulk)
    """
    # Verify agent exists
    agent = await get_chatbot_details_by_agent_id(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    file_name = ""
    description = []

    try:
        # Priority 1: JSON body
        if content_type.startswith("application/json"):
            if raw_body:
                data = json.loads(raw_body.decode())
                if "tables" in data:
                    description = [
                        {table["table_name"]: table["description"]}
                        for table in data["tables"]
                    ]
                else:
                    raise HTTPException(status_code=400, detail="JSON body must contain 'tables' array")
        # Priority 2: File upload
        elif file and file.filename:
            if table_descriptions_form and table_descriptions_form not in [None, "", "string"]:
                raise HTTPException(status_code=400, detail="Provide either 'file' or 'table_descriptions', not both")

            if file.filename.endswith('.json'):
                contents = await file.read()
                data = json.loads(contents.decode('utf-8'))
                if "tables" in data:
                    description = [
                        {table["table_name"]: table["description"]}
                        for table in data["tables"]
                    ]
                else:
                    raise HTTPException(status_code=400, detail="JSON file must contain 'tables' array")
                file_name = file.filename
            else:
                description, file_name = await common_utils.extract_from_csv(file, mode="table_description")
        # Priority 3: Form field JSON string
        elif table_descriptions_form and table_descriptions_form not in [None, "", "string"]:
            data = json.loads(table_descriptions_form)
            if "tables" in data:
                description = [
                    {table["table_name"]: table["description"]}
                    for table in data["tables"]
                ]
            elif "descriptions" in data:
                description = data["descriptions"]
            else:
                description = data
        else:
            raise HTTPException(status_code=400, detail="Provide tables via JSON body, file upload, or table_descriptions field")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error loading data: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Error loading data: {str(e)}")

    if not description:
        raise HTTPException(status_code=400, detail="No table descriptions provided")

    # Get database tables
    db_details = await database_db_utils.get_db_connection(None, agent_id)
    tables = []
    if db_details.get("status") and db_details.get("db_details"):
        tables = await database_db_utils.get_all_tables(db_details["db_details"])

    # Build description mapping
    description_final = []
    description_map = {list(entry.keys())[0]: entry for entry in description}

    if tables:
        for table in tables:
            if table in description_map:
                description_final.append(description_map[table])
            else:
                description_final.append({table: ""})
        entry_flags = {table: 1 for table in tables}
    else:
        description_final = description
        entry_flags = {list(entry.keys())[0]: 1 for entry in description}

    db_res = await table_description_db_utils.upload_to_db_table_description(
        None, agent_id, file_name, "", description_final, entry_flags
    )

    if db_res and db_res.get("status"):
        table_not_found = []
        if tables:
            for table in description_map.keys():
                if table not in tables:
                    table_not_found.append(table)
        
        message = "Table descriptions uploaded successfully"
        if table_not_found:
            message += f". Note: Tables {table_not_found} not found in database"

        return {
            "status": "success",
            "tables_added": len(description_map),
            "message": message
        }

    raise HTTPException(status_code=500, detail=f"Table descriptions failed to upload. Database response: {db_res}")

async def update_agent_table_descriptions(
    agent_id: str, 
    content_type: str, 
    raw_body: bytes = None, 
    file: Optional[UploadFile] = None, 
    table_descriptions_form: Optional[str] = None
) -> Dict[str, Any]:
    """
    Update table descriptions for an agent (bulk)
    """
    # Verify agent exists
    agent = await get_chatbot_details_by_agent_id(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    file_name = ""
    update_request = []

    try:
        # Priority 1: JSON body
        if content_type.startswith("application/json"):
            if raw_body:
                data = json.loads(raw_body.decode())
                if "tables" in data:
                    update_request = [
                        {table["table_name"]: table["description"]}
                        for table in data["tables"]
                    ]
                else:
                    raise HTTPException(status_code=400, detail="JSON body must contain 'tables' array")
        # Priority 2: File upload
        elif file and file.filename:
            if table_descriptions_form and table_descriptions_form not in [None, "", "string"]:
                raise HTTPException(status_code=400, detail="Provide either 'file' or 'table_descriptions', not both")

            if file.filename.endswith('.json'):
                contents = await file.read()
                data = json.loads(contents.decode('utf-8'))
                if "tables" in data:
                    update_request = [
                        {table["table_name"]: table["description"]}
                        for table in data["tables"]
                    ]
                else:
                    raise HTTPException(status_code=400, detail="JSON file must contain 'tables' array")
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
            data = json.loads(table_descriptions_form)
            if "tables" in data:
                update_request = [
                    {table["table_name"]: table["description"]}
                    for table in data["tables"]
                ]
            elif "descriptions" in data:
                update_request = data["descriptions"]
            else:
                update_request = data
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
    db = await table_description_db_utils.list_table_description_from_db(None, agent_id)
    db_dict = {}
    if db and db.get("record") and db.get("record").description:
        existing_desc = db.get("record").description
        if isinstance(existing_desc, str):
            existing_desc = json.loads(existing_desc)
        if isinstance(existing_desc, list):
            for item in existing_desc:
                if isinstance(item, dict):
                    db_dict.update(item)

    # Get database tables
    db_details = await database_db_utils.get_db_connection(None, agent_id)
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
        None, agent_id, file_name, description=final_db_records
    )

    if db_res and db_res.get("status"):
        message = "Table descriptions updated successfully"
        if table_not_found:
            message += f". Note: Tables {table_not_found} not found in database"
        return {"status": "success", "message": message}

    raise HTTPException(status_code=500, detail="Table descriptions failed to be updated")

async def delete_agent_table_descriptions(agent_id: str, table_names: List[str]) -> bool:
    """
    Delete table descriptions for an agent
    """
    # Verify agent exists
    agent = await get_chatbot_details_by_agent_id(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    if not table_names:
        raise HTTPException(status_code=400, detail="table_names is required")

    db = await table_description_db_utils.list_table_description_from_db(None, agent_id)
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

        for table_name in table_names:
            if table_name not in existing_table_names:
                raise HTTPException(status_code=404, detail=f"Table {table_name} not present in the existing table descriptions")

        for d in description:
            for key in table_names:
                d.pop(key, None)

        for key in table_names:
            description.append({key: ""})

        cleaned_data = [d for d in description if d]
        db_res = await table_description_db_utils.delete_table_descriptions_db(None, agent_id, cleaned_data)
        
        if db_res and db_res.get("status"):
            return True

    raise HTTPException(status_code=500, detail="Table descriptions failed to be deleted")

async def get_agent_high_cardinality_columns(agent_id: str, user_id: str = None) -> List[Dict[str, Any]]:
    """
    Get high cardinality columns for an agent
    """
    result = await table_description_db_utils.get_high_cardinality_columns(user_id, agent_id)
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

async def set_agent_high_cardinality_columns(agent_id: str, user_id: str, columns_data: List[Dict[str, str]]) -> Dict[str, Any]:
    """
    Set high cardinality columns for an agent
    """
    if not columns_data:
        raise HTTPException(status_code=400, detail="No valid high cardinality columns provided")

    db = await table_description_db_utils.get_high_cardinality_columns(user_id, agent_id)
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

    result = await table_description_db_utils.upload_high_cardinality_columns(user_id, agent_id, existing_hc)
    if result and result.get("status"):
        return {"status": "success", "columns_configured": len(columns_data), "message": "High cardinality columns configured"}
    raise HTTPException(status_code=500, detail="Failed to configure high cardinality columns")

async def delete_agent_high_cardinality_columns(agent_id: str, user_id: str, columns_to_remove: List[Dict[str, str]]) -> Dict[str, Any]:
    """
    Delete specific high cardinality columns for an agent
    """
    if not columns_to_remove:
        raise HTTPException(status_code=400, detail="No columns specified for removal")

    db = await table_description_db_utils.get_high_cardinality_columns(user_id, agent_id)
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

    result = await table_description_db_utils.upload_high_cardinality_columns(user_id, agent_id, existing_hc)
    if result and result.get("status"):
        return {"status": "success", "columns_removed": removed_count, "message": "High cardinality columns removed"}
    raise HTTPException(status_code=500, detail="Failed to remove high cardinality columns")

async def get_specific_agent_table_description(agent_id: str, table_name: str) -> Dict[str, Any]:
    """
    Get specific table description
    """
    # Verify agent exists
    agent = await get_chatbot_details_by_agent_id(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    db = await table_description_db_utils.list_table_description_from_db(None, agent_id)
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

async def update_specific_agent_table_description(agent_id: str, table_name: str, body: Any) -> Dict[str, Any]:
    """
    Update specific table description
    """
    # Verify agent exists
    agent = await get_chatbot_details_by_agent_id(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    db = await table_description_db_utils.list_table_description_from_db(None, agent_id)
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
        entry_flags[table_name] = 1 if body.is_included else 0

    db_res = await table_description_db_utils.upload_to_db_table_description(
        None, agent_id, record.file_name or "", record.url or "", description, entry_flags
    )
    if db_res and db_res.get("status"):
        return {"status": "success", "message": "Table description updated"}
    raise HTTPException(status_code=500, detail="Failed to update table description")

async def delete_specific_agent_table_description(agent_id: str, table_name: str) -> Dict[str, Any]:
    """
    Delete specific table description
    """
    # Verify agent exists
    agent = await get_chatbot_details_by_agent_id(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    # Get existing descriptions
    db = await table_description_db_utils.list_table_description_from_db(None, agent_id)

    if not (db and db.get("status") and db.get("record")):
        raise HTTPException(status_code=404, detail=f"No table descriptions found for agent {agent_id}")

    record = db.get("record")
    description = record.description

    if isinstance(description, str):
        try:
            description = json.loads(description)
        except:
            description = []

    # Check if table exists
    table_found = False
    for item in description:
        if isinstance(item, dict) and table_name in item:
            table_found = True
            break

    if not table_found:
        raise HTTPException(status_code=404, detail=f"Table {table_name} not found")

    # Remove the table and add empty entry
    description = [d for d in description if not (isinstance(d, dict) and table_name in d)]
    description.append({table_name: ""})

    # Update database
    db_result = await table_description_db_utils.delete_table_descriptions_db(
        None, agent_id, description
    )

    if db_result and db_result.get("status"):
        return {
            "status": "success",
            "message": "Table description deleted"
        }

    raise HTTPException(status_code=500, detail="Failed to delete table description")

async def update_agent_table_visibility(agent_id: str, table_name: str, is_included: bool) -> Dict[str, Any]:
    """
    Include/Exclude a specific table
    """
    # Verify agent exists
    agent = await get_chatbot_details_by_agent_id(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    # Get existing entry_flags
    db = await table_description_db_utils.list_table_description_from_db(None, agent_id)

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
    entry_flags[table_name] = 1 if is_included else 0

    # Update database
    db_result = await table_description_db_utils.upload_to_db_include_or_exclude_table_names(
        None, agent_id, entry_flags
    )

    if db_result and db_result.get("status"):
        return {
            "status": "success",
            "table_name": table_name,
            "is_included": is_included,
            "message": "Table visibility updated"
        }

    raise HTTPException(status_code=500, detail="Failed to update table visibility")

async def update_agent_bulk_table_visibility(agent_id: str, tables_visibility: List[Any]) -> Dict[str, Any]:
    """
    Bulk include/exclude tables
    """
    # Verify agent exists
    agent = await get_chatbot_details_by_agent_id(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    # Get existing entry_flags
    db = await table_description_db_utils.list_table_description_from_db(None, agent_id)

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
        entry_flags[table_item.table_name] = 1 if table_item.is_included else 0

    # Update database
    db_result = await table_description_db_utils.upload_to_db_include_or_exclude_table_names(
        None, agent_id, entry_flags
    )

    if db_result and db_result.get("status"):
        return {
            "status": "success",
            "updated_count": len(tables_visibility),
            "message": "Table visibility updated"
        }

    raise HTTPException(status_code=500, detail="Failed to update table visibility")

