from typing import Optional
import random
import uuid
import re
import csv
from datetime import date, datetime
from decimal import Decimal

from fastapi import HTTPException, Query
from pydantic import ValidationError
# import sqlparse
# from sqlparse.sql import IdentifierList, Identifier
# from sqlparse.tokens import Keyword, DML

from database_connection.services.logger import logger
from database_connection.services.pydantic_models_auth import GetDbConnectionRequest

def serialize_db_value(value):
    """
    Convert non-JSON-serializable database values to JSON-serializable formats.
    Handles date, datetime, Decimal, and other common database types.
    """
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    elif isinstance(value, Decimal):
        return float(value)
    elif isinstance(value, bytes):
        return value.decode('utf-8', errors='ignore')
    elif isinstance(value, (list, tuple)):
        return [serialize_db_value(item) for item in value]
    elif isinstance(value, dict):
        return {key: serialize_db_value(val) for key, val in value.items()}
    else:
        return value



def validate_database_request(engine: str, host: str, db_name: str, port: int) -> tuple[bool, str]:
    """
    Validate database connection request parameters using standardized error message format.
    Returns: (is_valid, error_message)
    
    Uses same error message categories and wording as _friendly_db_error() in database_db_utils.py:
    - HOST_INVALID: Hostname format or resolution issues
    - DB_NOT_FOUND: Database name missing or doesn't exist
    - PORT_OR_NETWORK: Port number or network connectivity issues
    - AUTH_*: Authentication errors
    - DB_ERROR: Database-level errors
    """
    engine = (engine or "").lower()
    
    # 1. Validate engine
    valid_engines = ["postgresql", "mysql", "sqlite"]
    if engine not in valid_engines:
        return False, f"Invalid database engine: {engine}. Supported engines are: {', '.join(valid_engines)}."
    
    # 2. Validate hostname
    if not host:
        return False, f"HOST_INVALID: Database hostname cannot be empty. Please provide a valid hostname."
    
    if ".." in host:
        return False, f"HOST_INVALID: Invalid hostname format for {engine}: contains invalid characters (such as '..') or is malformed. Please verify the database hostname."
    
    if host.startswith(".") or host.endswith("."):
        return False, f"HOST_INVALID: Invalid hostname format for {engine}: cannot start or end with a dot. Please verify the database hostname."
    
    # 3. Validate database name (not required for SQLite)
    if engine != "sqlite" and (not db_name or not db_name.strip()):
        return False, f"DB_NOT_FOUND: Database name is required for {engine.capitalize()} databases. Please verify the database name."
    
    # 4. PostgreSQL may be published on any valid TCP port by an installation.
    if engine == "postgresql":
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            return False, f"PORT_OR_NETWORK: Invalid port for PostgreSQL: {port}. Use a TCP port between 1 and 65535."
    elif engine == "mysql":
        if port != 3306:
            return False, f"PORT_OR_NETWORK: Invalid port for MySQL: {port}. MySQL standard port is 3306."
    elif engine == "sqlite":
        if port != 0:
            return False, f"PORT_OR_NETWORK: Invalid port for SQLite: {port}. SQLite does not use network ports (port must be 0)."
    
    return True, ""

def serialize_db_result(db_result):
    """
    Serialize database query results to be JSON-compatible.
    Handles lists of tuples, lists of dicts, or other formats.
    """
    if not db_result:
        return db_result

    if isinstance(db_result, list):
        return [serialize_db_value(row) for row in db_result]
    else:
        return serialize_db_value(db_result)

def generate_bot_id() -> str:
    unique_str = str(uuid.uuid4()).split("-")[0]
    return f"NL2SQL_{unique_str}".upper()

def check_table_name_in_description(description, table_names):
    # Check if table_name exist in the table descriptions or not
    existing_table_names = []
    for desc in description:
        existing_table_names.extend(desc.keys())
    print("existing_table_names", existing_table_names)
    
    for table in table_names:
        if table not in existing_table_names:
            return table, False
    
    return "",True

def generate_response(query, refined_query, sql_query, db_result, response_text, chat_id, session_id, x_label, y_label, graph_info, graph_type, post_processing_query, selected_table,include_debug=False, include_graph=False):
    result = {
        "response": response_text,
        "session_id": session_id,
        "chat_id": chat_id
    }

    if include_debug:
        # Serialize db_result to handle date/datetime objects
        serialized_db_result = serialize_db_result(db_result)
        result["debug_info"] = {
            "query": query,
            "refined_query": refined_query,
            "sql_query": sql_query,
            "db_result": serialized_db_result,
            "selected_table": selected_table
        }
    else:
        result["debug_info"] = None

    if include_graph:
        if graph_info is not None:
            graph_output =  {
                "suggestion" : graph_type,
                "x_label" : x_label,
                "y_label" : y_label,
                "data" : graph_info
                # "post_processing_query": post_processing_query
            }
        else:
            graph_output = {
                "suggestion" : graph_type,
                "x_label" : None,
                "y_label" : None,
                "data" : graph_info
                # "post_processing_query": post_processing_query
            }
        
        result["graph_output"] = graph_output
    else:
        result["graph_output"] = None
        
    return result

def get_conversation_string(conversation):
    conversation_str = ""
    for turn in conversation:
        role = turn['role']
        content = turn['content']
        conversation_str += f"{role.capitalize()}: {content}\n"
    return conversation_str

def generate_user_id(firstname: Optional[str], lastname: Optional[str]) -> str:
    if firstname and lastname:
        base_id = f"{firstname[:3]}{lastname[:3]}".lower()  # First 3 letters of both names
    elif firstname:
        base_id = firstname[:6].lower()  # First 6 letters of firstname
    elif lastname:
        base_id = lastname[:6].lower()  # First 6 letters of lastname
    else:
        base_id = "user_id"  # Default base if no names are provided
    
    
    unique_str = str(uuid.uuid4()).split("-")[0]
    return f"{base_id}_{unique_str}"



def convert_google_drive_to_downloadable(url):
    if "drive.google.com" in url and "/file/d/" in url:
        file_id = url.split("/file/d/")[1].split("/")[0]
        return f"https://drive.google.com/uc?id={file_id}&export=download"
    return url



def convert_google_sheet_to_csv(url):
    """
    Convert Google Sheets URL to CSV export link.
    """
    sheet_id = re.findall(r'/spreadsheets/d/([^/]+)', url)
    if sheet_id:
        return f"https://docs.google.com/spreadsheets/d/{sheet_id[0]}/export?format=csv"
    return url

def transform_two_variable_graph_data(data):
    if not data or not isinstance(data, list) or len(data) == 0:
        logger.error("Failed to extract x_label and y_label: data is empty or not a list")
        return None, None, None
    try:
        first_dict = data[0]
        # Retrieve the first and last keys
        x_label = next(iter(first_dict))
        y_label = next(reversed(first_dict))
        # Output the results
        print(f"x_label: {x_label}, y_label: {y_label}")
    except (IndexError, AttributeError) as e:
        logger.error("Failed to extract x_label and y_label: %s", e)
        return None, None, None

    transformed_data = []
    for item in data:
        try:
            label = item[x_label]
            value = int(float(item[y_label]))
            transformed_data.append({"label": label, "value": value})
        except (ValueError, TypeError) as e:
            logger.warning("Skipping item due to conversion error: %s", e)
            continue
        except KeyError as e:
            logger.warning("Skipping item due to missing key: %s", e)
            continue

    return x_label, y_label, transformed_data

async def extract_from_csv(file, mode: str = "table_description"):
    contents = await file.read()
    csv_data = contents.decode('utf-8').splitlines()
    reader = csv.DictReader(csv_data)

    fieldnames = reader.fieldnames or []
    logger.info(f"fieldnames: {fieldnames}")

    # Determine keys based on mode
    if mode == "table_description":
        key1, key2 = ('table_name', 'description')
        if '\ufefftable_name' in fieldnames:
            key1 = '\ufefftable_name'
    elif mode == "nl2sql_examples":
        key1, key2 = ('natural_query', 'sql_query')
        if '\ufeffnatural_query' in fieldnames:
            key1 = '\ufeffnatural_query'
    else:
        raise ValueError(f"Unsupported mode: {mode}")

    # Read all rows
    rows = list(reader)
    if rows:
        logger.info(f"First row: {rows[0]}")
    else:
        logger.warning("CSV file is empty or only contains headers.")
        rows = []

    # Safely build the result list
    result = []
    for i, row in enumerate(rows):
        try:
            value1 = row.get(key1, "").strip()
            value2 = row.get(key2, "").strip()

            if not value1:
                logger.warning(f"Skipping empty or incomplete row at index {i}: {row}")
                continue

            result.append({value1: value2})
        except Exception as e:
            logger.error(f"Error processing row {i}: {e} | Row data: {row}")

    file_name = file.filename
    return result, file_name

def validate_get_table_description_query_params(
    user_id: Optional[str] = Query(None),
    chatbot_id: str = Query(...),
) -> GetDbConnectionRequest:
    try:
        return GetDbConnectionRequest(user_id=user_id, chatbot_id=chatbot_id)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=e.errors())  
      

def validate_get_db_connection_query_params(
    user_id: Optional[str] = Query(None),
    chatbot_id: str = Query(...),
) -> GetDbConnectionRequest:
    try:
        return GetDbConnectionRequest(user_id=user_id, chatbot_id=chatbot_id)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=e.errors())
# import re
# import sqlglot
# from sqlglot.expressions import Table, Column, Literal

# def extract_identifiers_with_sqlglot(sql, known_tables):
#     try:
#         parsed = sqlglot.parse_one(sql)
#     except Exception as e:
#         logger.error(f"Failed to parse SQL: {e}")
#         return set(), set()

#     # Use full table name including schema if present
#     all_tables = {
#         table.sql(dialect='') for table in parsed.find_all(Table)
#     }

#     # Include literals that match known tables (e.g., in WHERE table_name = 'some_table')
#     literal_tables = {
#         lit.this for lit in parsed.find_all(Literal)
#         if isinstance(lit.this, str) and lit.this in known_tables
#     }

#     all_tables |= literal_tables

#     # Extract columns, ignoring '*'
#     columns = {col.name for col in parsed.find_all(Column) if col.name != '*'}

#     return columns, all_tables

# def validate_sql_query(query, allowed_columns, allowed_tables):
#     logger.info(f"Validating SQL query: {query}")

#     # Disallow dangerous SQL operations
#     disallowed_statements = ["DELETE", "INSERT", "UPDATE", "DROP", "ALTER"]
#     for statement in disallowed_statements:
#         if re.search(rf"\b{statement}\b", query, re.IGNORECASE):
#             logger.error(f"Query contains disallowed statement: {statement}")
#             return False

#     try:
#         parsed = sqlglot.parse_one(query)
#     except Exception as e:
#         logger.error(f"Failed to parse SQL: {e}")
#         return False

#     used_columns, used_tables = extract_identifiers_with_sqlglot(query, allowed_tables)

#     logger.info(f"Used columns: {used_columns}, Used tables: {used_tables}")

#     for tbl in used_tables:
#         if tbl not in allowed_tables and not tbl.startswith("information_schema."):
#             logger.error(f"Disallowed table used: {tbl}")
#             return False
        
#     from langchain_openai import ChatOpenAI
#     from pydantic import BaseModel, Field
#     class SqlValidation(BaseModel):
#         is_valid: bool = Field(description="Whether the SQL query is valid or not")
#         reason: str = Field(description="Reason for the validity of the SQL query")
#     # get llm to answer if the prompt is valid or not
#     llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
#     prompt = f"""
#         Is the following SQL query valid? It should be syntactically correct and use only the tables that are allowed. 
#         The allowed tables are: {allowed_tables} \n
#         sql query: {query}"""
#     response = llm.with_structured_output(SqlValidation).invoke(prompt)
#     logger.info(f"LLM response: {response}")
#     if response.is_valid:
#         return True
#     else:
#         return False
    
#     # for col in used_columns:
#     #     if col not in allowed_columns:
#     #         logger.error(f"Disallowed column used: {col}")
#     #         return False

#     return True

