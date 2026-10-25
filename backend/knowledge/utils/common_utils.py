from typing import Optional
import random
import uuid
import re
import csv
from datetime import date, datetime
from decimal import Decimal
# import sqlparse
# from sqlparse.sql import IdentifierList, Identifier
# from sqlparse.tokens import Keyword, DML

from knowledge.services.logger import logger

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

    # Read all rows for logging
    rows = list(reader)
    if rows:
        logger.info(f"First row: {rows[0]}")
    else:
        logger.warning("CSV file is empty or only contains headers.")
        rows = []

    # Reset file pointer and re-read for actual processing
    await file.seek(0)
    contents = await file.read()
    logger.info(f"[extract_from_csv] After seek(0), read {len(contents)} bytes.")
    csv_data = contents.decode('utf-8').splitlines()
    logger.info(f"[extract_from_csv] After seek(0), first 2 lines: {csv_data[:2]}")
    reader = csv.DictReader(csv_data)

    fieldnames = reader.fieldnames or []
    logger.info(f"[extract_from_csv] After seek(0), fieldnames: {fieldnames}")
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

    # Read all rows for processing
    rows = list(reader)
    logger.info(f"[extract_from_csv] After seek(0), number of rows: {len(rows)}")
    if rows:
        logger.info(f"[extract_from_csv] After seek(0), first row: {rows[0]}")

    # Safely build the result list
    result = []
    for i, row in enumerate(rows):
        try:
            value1 = row.get(key1, "").strip()
            value2 = row.get(key2, "").strip()

            if not value1:
                logger.warning(f"Skipping empty or incomplete row at index {i}: {row}")
                continue

            # For nl2sql_examples mode, return dict with explicit keys
            if mode == "nl2sql_examples":
                result.append({'natural_query': value1, 'sql_query': value2})
            else:
                result.append({value1: value2})
        except Exception as e:
            logger.error(f"Error processing row {i}: {e} | Row data: {row}")

    file_name = file.filename
    return result, file_name