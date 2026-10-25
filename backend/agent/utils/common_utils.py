from typing import Optional
import math
import random
import uuid
import re
import csv
from datetime import date, datetime, time as dt_time, timedelta
from decimal import Decimal

from sqlalchemy import select
from agent.services.logger import logger
from agent.services.sqlmodel_session import async_session
from models.sql_models import Users

def serialize_db_value(value):
    """
    Convert non-JSON-serializable database values to JSON-serializable formats.
    Handles date, datetime, Decimal, and other common database types.
    """
    if isinstance(value, (date, datetime, dt_time)):
        return value.isoformat()
    elif isinstance(value, timedelta):
        # A Postgres INTERVAL arrives as a timedelta, which json.dumps cannot
        # encode - the request died with a 500 before this branch existed.
        # "How long does a customer stay?" is answered by avg(ended_ts -
        # started_ts), so an interval reaches this function on ordinary
        # questions. str() matches what final_answer._make_json_safe already
        # produces for the same type, so the two paths agree.
        return str(value)
    elif isinstance(value, Decimal):
        decimal_as_float = float(value)
        return None if not math.isfinite(decimal_as_float) else decimal_as_float
    elif isinstance(value, float):
        return None if not math.isfinite(value) else value
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


def _infer_column_type(values):
    """Return a UI-friendly type label inferred from the first non-null value."""
    for v in values:
        if v is None:
            continue
        if isinstance(v, bool):
            return "boolean"
        if isinstance(v, int):
            return "integer"
        if isinstance(v, (float, Decimal)):
            return "number"
        if isinstance(v, datetime):
            return "datetime"
        if isinstance(v, date):
            return "date"
        if isinstance(v, (bytes, str)):
            return "string"
        if isinstance(v, (list, tuple)):
            return "array"
        if isinstance(v, dict):
            return "object"
        return type(v).__name__
    return "null"


def build_data_block(db_columns, db_result, row_limit=None):
    """
    Build a UI-friendly tabular data block from raw SQL results.

    Returns:
        {
          "columns": [{"name": str, "type": str}, ...],
          "rows": [{column_name: value, ...}, ...],
          "row_count": int,         # total rows produced by SQL
          "truncated": bool         # True if row_limit clipped the payload
        }
    """
    if not db_result:
        return {"columns": [], "rows": [], "row_count": 0, "truncated": False}

    # Resolve column names — prefer the explicit list, otherwise infer from first row.
    if not db_columns:
        first = db_result[0]
        if isinstance(first, dict):
            db_columns = list(first.keys())
        elif isinstance(first, (list, tuple)):
            db_columns = [f"col_{i}" for i in range(len(first))]
        else:
            db_columns = ["value"]

    total = len(db_result)
    limited = db_result if (row_limit is None or total <= row_limit) else db_result[:row_limit]

    rows = []
    for row in limited:
        if isinstance(row, dict):
            rows.append({col: serialize_db_value(row.get(col)) for col in db_columns})
        elif isinstance(row, (list, tuple)):
            rows.append({
                col: serialize_db_value(row[i]) if i < len(row) else None
                for i, col in enumerate(db_columns)
            })
        else:
            rows.append({db_columns[0]: serialize_db_value(row)})

    column_specs = []
    for i, col in enumerate(db_columns):
        col_vals = []
        for r in limited:
            if isinstance(r, dict):
                col_vals.append(r.get(col))
            elif isinstance(r, (list, tuple)):
                col_vals.append(r[i] if i < len(r) else None)
            else:
                col_vals.append(r)
        column_specs.append({"name": col, "type": _infer_column_type(col_vals)})

    return {
        "columns": column_specs,
        "rows": rows,
        "row_count": total,
        "truncated": len(limited) < total,
    }

def generate_bot_id() -> str:
    unique_str = str(uuid.uuid4()).split("-")[0]
    return f"NL2SQL_{unique_str}".upper()

def check_table_name_in_description(description, table_names):
    # Check if table_name exist in the table descriptions or not
    existing_table_names = []
    for desc in description:
        existing_table_names.extend(desc.keys())
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
        if isinstance(graph_info, dict):
            result["graph_output"] = graph_info
        elif graph_info is not None:
            graph_output =  {
                "suggestion" : graph_type,
                "x_label" : x_label,
                "y_label" : y_label,
                "data" : graph_info
                # "post_processing_query": post_processing_query
            }
            result["graph_output"] = graph_output
        else:
            result["graph_output"] = None
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
    # Validate input
    if not data or not isinstance(data, list):
        logger.error("Failed to extract x_label and y_label: empty or invalid data")
        return None, None, None

    first_item = data[0]
    if not isinstance(first_item, dict) or len(first_item) < 2:
        logger.error("Failed to extract x_label and y_label: first item is not a dict with >=2 keys")
        return None, None, None

    # Determine x and y keys robustly
    keys = list(first_item.keys())
    x_label = keys[0]
    y_label = keys[-1] if len(keys) > 1 else None
    if y_label is None or x_label == y_label:
        logger.error("Failed to determine distinct x and y labels from keys: %s", keys)
        return None, None, None

    transformed_data = []
    for item in data:
        if not isinstance(item, dict):
            logger.warning("Skipping non-dict item: %s", item)
            continue
        try:
            label = item.get(x_label)
            value_raw = item.get(y_label)
            if label is None or value_raw is None:
                raise KeyError(f"Missing keys {x_label}/{y_label}")
            value = int(float(value_raw))
            transformed_data.append({"label": label, "value": value})
        except (ValueError, TypeError) as e:
            logger.warning("Skipping item due to conversion error: %s | item=%s", e, item)
            continue
        except KeyError as e:
            logger.warning("Skipping item due to missing key: %s | item=%s", e, item)
            continue

    if not transformed_data:
        logger.error("No valid data points after transformation")
        return x_label, y_label, []

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
        # Accept the UI template's short names (question,sql) as well as natural_query,sql_query.
        key1 = next((k for k in ('natural_query', '\ufeffnatural_query', 'question', '\ufeffquestion') if k in fieldnames), 'natural_query')
        key2 = 'sql_query' if 'sql_query' in fieldnames else ('sql' if 'sql' in fieldnames else 'sql_query')
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

async def extract_user_from_email(session_data):
    """
    Return the `user_id` from the provided session data fetched from auth service.
    Falls back to `all_claims.sub` if `user_id` is missing.
    """

    
    user_id = await get_user_id_from_email(session_data.get("email"))
    if user_id:
        return user_id
    else:
        if not session_data:
            return None
        user_id = session_data.get("user_id")
        if user_id:
            return user_id
        claims = session_data.get("all_claims", {}) or {}
        return claims.get("sub")

async def get_user_id_from_email(email):
    """Retrieve user ID from the database based on the email."""
    try:
        async with async_session() as session:
            statement = select(Users.user_id).where(Users.email_id == email)
            result = await session.execute(statement)
            user_id = result.scalar_one_or_none()

        if user_id:
            logger.info(f"Retrieved user ID for email: {email}")
            return user_id
        else:
            logger.info(f"No user ID found for email: {email}")
            return None
    except Exception as e:
        logger.error(f"Database error occurred during get_user_id_from_email: {str(e)}")
        return None

