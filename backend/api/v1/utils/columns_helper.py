from typing import List, Dict, Any, Optional
import pymysql
import psycopg2
from fastapi import HTTPException
from chatbot_management.services.logger import logger
from knowledge.db_utils import database_db_utils, column_description_db_utils
from agent.db_utils.database_db_utils import get_primary_db_id, get_db_connection_by_id
from models.sql_models import ChatbotDetails
from chatbot_management.services.sqlmodel_session import get_async_session
from sqlmodel import select


async def _resolve_db(user_id, agent_id, db_id):
    """Resolve db_id to primary when omitted and return (db_id, db_details)."""
    db_id = db_id or await get_primary_db_id(agent_id)
    if db_id:
        res = await get_db_connection_by_id(agent_id, db_id)
    else:
        res = await database_db_utils.get_db_connection(user_id, agent_id)
    if not res.get("status") or not res.get("db_details"):
        raise HTTPException(status_code=404, detail="Database connection not found for this agent")
    return db_id, res["db_details"]

def get_table_columns_from_db(db_details: dict, table_name: str) -> List[Dict]:
    """
    Get column information from database schema using INFORMATION_SCHEMA
    """
    try:
        columns = []

        if db_details['db_engine'] == 'mysql':
            conn = pymysql.connect(
                host=db_details['db_host'],
                user=db_details['db_user'],
                password=db_details['db_password'],
                database=db_details['db_name'],
                port=db_details.get('db_port', 3306)
            )
            with conn.cursor() as cursor:
                # Get column information
                cursor.execute(f"""
                    SELECT
                        COLUMN_NAME,
                        DATA_TYPE,
                        IS_NULLABLE,
                        COLUMN_KEY
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
                    ORDER BY ORDINAL_POSITION
                """, (db_details['db_name'], table_name))

                for row in cursor.fetchall():
                    columns.append({
                        "column_name": row[0],
                        "data_type": row[1],
                        "is_nullable": row[2] == 'YES',
                        "is_primary_key": row[3] == 'PRI'
                    })
            conn.close()

        elif db_details['db_engine'] == 'postgresql':
            conn = psycopg2.connect(
                host=db_details['db_host'],
                user=db_details['db_user'],
                password=db_details['db_password'],
                database=db_details['db_name'],
                port=db_details.get('db_port', 5432)
            )
            with conn.cursor() as cursor:
                # Get column information
                cursor.execute("""
                    SELECT
                        c.column_name,
                        c.data_type,
                        c.is_nullable,
                        CASE WHEN pk.column_name IS NOT NULL THEN true ELSE false END as is_primary_key
                    FROM information_schema.columns c
                    LEFT JOIN (
                        SELECT ku.column_name
                        FROM information_schema.table_constraints tc
                        JOIN information_schema.key_column_usage ku
                            ON tc.constraint_name = ku.constraint_name
                        WHERE tc.constraint_type = 'PRIMARY KEY'
                            AND tc.table_schema = 'public'
                            AND tc.table_name = %s
                    ) pk ON c.column_name = pk.column_name
                    WHERE c.table_schema = 'public' AND c.table_name = %s
                    ORDER BY c.ordinal_position
                """, (table_name, table_name))

                for row in cursor.fetchall():
                    columns.append({
                        "column_name": row[0],
                        "data_type": row[1],
                        "is_nullable": row[2] == 'YES',
                        "is_primary_key": row[3]
                    })
            conn.close()

        else:
            raise ValueError(f"Unsupported database engine: {db_details['db_engine']}")

        return columns
    except Exception as e:
        logger.error(f"Error getting columns from database: {str(e)}")
        raise

async def verify_agent_exists(agent_id: str):
    """Verify that an agent exists in the database"""
    async for session in get_async_session():
        agent_result = await session.execute(
            select(ChatbotDetails).where(ChatbotDetails.agent_id == agent_id)
        )
        agent = agent_result.scalar_one_or_none()
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
        return agent

async def get_columns_with_descriptions(user_id: str, agent_id: str, table_name: str, db_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Get all columns for a table and merge with our stored descriptions
    """
    # Verify agent exists
    await verify_agent_exists(agent_id)

    # Resolve DB (specific db_id or primary) and its connection
    db_id, db_details = await _resolve_db(user_id, agent_id, db_id)

    # Get columns from database schema
    columns = get_table_columns_from_db(db_details, table_name)

    # Get column descriptions from our database
    column_desc_result = await column_description_db_utils.get_column_descriptions(user_id, agent_id, table_name, db_id=db_id)
    column_descriptions = {}
    if column_desc_result.get("status") and column_desc_result.get("record"):
        column_descriptions = column_desc_result["record"].get("column_descriptions", {})

    # Format response
    column_list = [
        {
            "column_name": col["column_name"],
            "data_type": col["data_type"],
            "description": column_descriptions.get(col["column_name"], ""),
            "is_primary_key": col["is_primary_key"]
        }
        for col in columns
    ]

    return {
        "table_name": table_name,
        "columns": column_list
    }

async def update_table_column_descriptions(user_id: str, agent_id: str, table_name: str, body: Any, db_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Update column descriptions for a table (bulk)
    """
    # Verify agent exists
    await verify_agent_exists(agent_id)

    # Resolve DB (specific db_id or primary) and its connection
    db_id, db_details = await _resolve_db(user_id, agent_id, db_id)

    # Verify table exists in the database
    columns = get_table_columns_from_db(db_details, table_name)
    if not columns:
        raise HTTPException(status_code=404, detail=f"Table {table_name} not found in database")

    # Get existing column names from database
    existing_column_names = {col["column_name"] for col in columns}

    # Validate that all columns in the request exist in the table
    invalid_columns = []
    for col_update in body.columns:
        if col_update.column_name not in existing_column_names:
            invalid_columns.append(col_update.column_name)

    if invalid_columns:
        raise HTTPException(
            status_code=400,
            detail=f"Columns not found in table {table_name}: {', '.join(invalid_columns)}"
        )

    # Build column descriptions dictionary
    column_descriptions = {col.column_name: col.description for col in body.columns}

    # Store in database
    result = await column_description_db_utils.upload_column_descriptions(
        user_id, agent_id, table_name, column_descriptions, db_id=db_id
    )

    if result.get("status"):
        return {
            "status": "success",
            "columns_updated": len(body.columns),
            "message": "Column descriptions updated successfully"
        }
    else:
        raise HTTPException(status_code=500, detail=result.get("message", "Failed to update column descriptions"))

async def get_column_details(user_id: str, agent_id: str, table_name: str, column_name: str, db_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Get description for a specific column
    """
    # Verify agent exists
    await verify_agent_exists(agent_id)

    # Resolve DB (specific db_id or primary) and its connection
    db_id, db_details = await _resolve_db(user_id, agent_id, db_id)

    # Get columns from database schema
    columns = get_table_columns_from_db(db_details, table_name)

    # Find the specific column
    column_info = None
    for col in columns:
        if col["column_name"] == column_name:
            column_info = col
            break

    if not column_info:
        raise HTTPException(status_code=404, detail=f"Column {column_name} not found in table {table_name}")

    # Get column description from our database
    column_desc_result = await column_description_db_utils.get_column_descriptions(user_id, agent_id, table_name, db_id=db_id)
    description = ""
    if column_desc_result.get("status") and column_desc_result.get("record"):
        column_descriptions = column_desc_result["record"].get("column_descriptions", {})
        description = column_descriptions.get(column_name, "")

    return {
        "table_name": table_name,
        "column_name": column_info["column_name"],
        "data_type": column_info["data_type"],
        "description": description,
        "is_nullable": column_info["is_nullable"],
        "is_primary_key": column_info["is_primary_key"]
    }

async def update_column_details(user_id: str, agent_id: str, table_name: str, column_name: str, description: str, db_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Update description for a specific column
    """
    # Verify agent exists
    await verify_agent_exists(agent_id)

    # Resolve DB (specific db_id or primary) and its connection
    db_id, db_details = await _resolve_db(user_id, agent_id, db_id)

    # Verify column exists
    columns = get_table_columns_from_db(db_details, table_name)
    column_exists = any(col["column_name"] == column_name for col in columns)

    if not column_exists:
        raise HTTPException(status_code=404, detail=f"Column {column_name} not found in table {table_name}")

    # Update column description in database
    result = await column_description_db_utils.update_column_description(
        user_id, agent_id, table_name, column_name, description, db_id=db_id
    )

    if result.get("status"):
        return {
            "status": "success",
            "message": "Column description updated successfully"
        }
    else:
        raise HTTPException(status_code=500, detail=result.get("message", "Failed to update column description"))
