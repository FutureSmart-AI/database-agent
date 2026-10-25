import time
import json
from datetime import datetime, timedelta
from agent.db_utils.common_db_utils import get_connection
from agent.db_utils.common_postresql_utils import execute_sql_query, db_rows_affected_log
import pymysql
import psycopg2
from logger import logger
from sqlmodel import select
from typing import Optional
from models.sql_models import TableDescription
from agent.services.sqlmodel_session import get_async_session
from agent.db_utils.database_db_utils import get_primary_db_id
from otel_tracing import track_time

async def upload_to_db_table_description(user_id, chatbot_id, file_name='', url='', description='', entry_flags='', db_id: Optional[str] = None):
    try:
        db_id = db_id or await get_primary_db_id(chatbot_id)
        async for session in get_async_session():
            res = await session.execute(
                select(TableDescription).where(
                    TableDescription.user_id == user_id,
                    TableDescription.chatbot_id == chatbot_id,
                    TableDescription.db_id == db_id,
                )
            )
            record = res.first()
            if record:
                record = record[0]  # Unpack ORM object from tuple
                record.file_name = file_name
                record.url = url
                record.description = description
                record.entry_flags = entry_flags
            else:
                record = TableDescription(
                    user_id=user_id,
                    chatbot_id=chatbot_id,
                    db_id=db_id,
                    file_name=file_name,
                    url=url,
                    description=description,
                    entry_flags=entry_flags,
                    created_at=datetime.utcnow()
                )
                session.add(record)
            await session.commit()
            return {"message": "upload_to_db_table_description function executed", "status": True}
    except Exception as e:
        logger.error(f"Exception in upload_to_db_table_description: {str(e)}")
        return {"message": f"Error in upload_to_db_table_description: {str(e)}", "status": False}

async def update_table_description(user_id, chatbot_id, file_name='', description='', db_id: Optional[str] = None):
    try:
        db_id = db_id or await get_primary_db_id(chatbot_id)
        async for session in get_async_session():
            res = await session.execute(
                select(TableDescription).where(
                    TableDescription.user_id == user_id,
                    TableDescription.chatbot_id == chatbot_id,
                    TableDescription.db_id == db_id,
                )
            )
            record = res.first()
            if record:
                record = record[0]  # Unpack ORM object from tuple
                record.file_name = file_name
                record.description = description
                await session.commit()
                return {"message": "update_table_description function executed", "status": True}
            else:
                return {"message": "update_table_description function executed: No Record Found", "status": False}
    except Exception as e:
        logger.error(f"Exception in update_table_description: {str(e)}")
        return {"message": f"Error in update_table_description: {str(e)}", "status": False}

@track_time("DB: List Table Description")
async def list_table_description_from_db(user_id: str, agent_id: str, db_id: Optional[str] = None):
    """
    List table descriptions by agent_id.
    Queries by agent_id OR chatbot_id for backward compatibility.

    Args:
        user_id: Unused for filtering — a row is identified by (agent, db), not by whoever
            last wrote it. user_id on the row is an audit stamp of the acting user, so
            filtering on it hid descriptions from every caller except that one user (and
            hid job-generated rows, stamped NULL, from everyone). Kept in the signature
            because callers pass it positionally.
        agent_id: Agent ID
        db_id: Database ID (defaults to the agent's primary DB)
    """
    try:
        from sqlalchemy import or_
        db_id = db_id or await get_primary_db_id(agent_id)
        async for session in get_async_session():
            # Query by agent_id OR chatbot_id for backward compatibility, scoped to db_id
            query = select(TableDescription).where(
                or_(
                    TableDescription.chatbot_id == agent_id,
                    # TableDescription doesn't have agent_id column, so only query chatbot_id
                ),
                TableDescription.db_id == db_id,
            )

            res = await session.execute(query)
            record = res.first()
            if record:
                record = record[0]  # Unpack ORM object from tuple
                return {"record": record, "message": "list_table_description_from_db function executed", "status": True}
            else:
                return {"record": None, "message": "list_table_description_from_db function executed: No Record Found", "status": False}
    except Exception as e:
        logger.error(f"Exception in list_table_description_from_db: {str(e)}")
        return {"message": f"Error in list_table_description_from_db: {str(e)}", "status": False}

async def get_include_exclude_table_names(user_id, chatbot_id, db_id: Optional[str] = None):
    try:
        db_id = db_id or await get_primary_db_id(chatbot_id)
        with get_sqlmodel_session() as session:
            record = session.execute(
                select(TableDescription.entry_flags).where(
                    TableDescription.user_id == user_id,
                    TableDescription.chatbot_id == chatbot_id,
                    TableDescription.db_id == db_id,
                )
            ).first()
            if record is not None:
                return {"record": {"entry_flags": record}, "message": "get_include_exclude_table_names function executed", "status": True}
            else:
                return {"record": None, "message": "get_include_exclude_table_names function executed: No Record Found", "status": False}
    except Exception as e:
        logger.error(f"Exception in get_include_exclude_table_names: {str(e)}")
        return {"message": f"Error in get_include_exclude_table_names: {str(e)}", "status": False}

async def upload_to_db_include_or_exclude_table_names(user_id, chatbot_id, entry_flags, db_id: Optional[str] = None):
    try:
        db_id = db_id or await get_primary_db_id(chatbot_id)
        async for session in get_async_session():
            res = await session.execute(
                select(TableDescription).where(
                    TableDescription.user_id == user_id,
                    TableDescription.chatbot_id == chatbot_id,
                    TableDescription.db_id == db_id,
                )
            )
            record = res.first()
            if record:
                record = record[0]  # Unpack ORM object from tuple
                record.entry_flags = entry_flags
            else:
                record = TableDescription(
                    user_id=user_id,
                    chatbot_id=chatbot_id,
                    db_id=db_id,
                    entry_flags=entry_flags,
                    created_at=datetime.utcnow()
                )
                session.add(record)
            await session.commit()
            return {"message": "upload_to_db_include_or_exclude_table_names function executed", "status": True}
    except Exception as e:
        logger.error(f"Exception in upload_to_db_include_or_exclude_table_names: {str(e)}")
        return {"message": f"Error in upload_to_db_include_or_exclude_table_names: {str(e)}", "status": False}

async def delete_table_descriptions_db(user_id, chatbot_id, description, db_id: Optional[str] = None):
    try:
        db_id = db_id or await get_primary_db_id(chatbot_id)
        async for session in get_async_session():
            res = await session.execute(
                select(TableDescription).where(
                    TableDescription.user_id == user_id,
                    TableDescription.chatbot_id == chatbot_id,
                    TableDescription.db_id == db_id,
                )
            )
            record = res.first()
            if not record:
                return {"message": "delete_table_descriptions_db function executed: No Record Found", "status": False}
            record = record[0]  # Unpack ORM object from tuple
            record.description = description
            await session.commit()
            return {"message": "delete_table_descriptions_db function executed", "status": True}
    except Exception as e:
        logger.error(f"Exception in delete_table_descriptions_db: {str(e)}")
        return {"message": f"Error in delete_table_descriptions_db: {str(e)}", "status": False}

def get_db_connection(db_details):
    from database_connection.source_connection import open_source_connection
    return open_source_connection(db_details['db_details'])

# Function to fetch table names from the database
def get_table_names_from_db(db_details):
    connection = get_db_connection(db_details)
    try:
        table_names = []
        with connection.cursor() as cursor:
            if db_details['db_details']['db_engine'] == 'mysql':
                cursor.execute("SHOW TABLES")
                tables = cursor.fetchall()
                table_names = [table[0] for table in tables]
            elif db_details['db_details']['db_engine'] == 'postgresql':
                cursor.execute("""
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_type = 'BASE TABLE'
                """)
                tables = cursor.fetchall()
                table_names = [table[0] for table in tables]
            else:
                raise ValueError("Unsupported database engine")
            logger.info(f"table_names: {table_names}")
    finally:
        connection.close()
    return table_names

# Function to match table descriptions with actual tables
def match_table_names_with_db(table_flags, table_descriptions, db_table_names):
    # Get actual table names from the database
    # logger.info(f"Actual table names in the database: {table_names}")
    # db_table = [db_table_name for db_table_name in table_names]
    matched_tables = []
    
    # Iterate through the table descriptions and match with actual table names
    for table_desc in table_descriptions:
        for table_name, description in table_desc.items():
            if (table_name in db_table_names or table_name.lower() in db_table_names) and table_flags.get(table_name):  
                matched_tables.append({
                    table_name: description
                })
            else:
                logger.info(f"Table {table_name} excluded, flag: {table_flags.get(table_name)}, table_in_db: {table_name in db_table_names or table_name.lower() in db_table_names}")
            # elif table_name.lower() in db_table: 
            #     matched_tables.append({
            #         table_name.lower() : description
            #     })
    return matched_tables

import mysql.connector
def get_unique_values_for_columns(db_details, table_name, column_names):
    try:
        start_time = time.time()
        
        # Connect to MySQL database
        logger.info("Table dbutils - get_unique_values_for_columns")
        connection = get_db_connection(db_details)
        
        with connection.cursor() as cursor:
            unique_values = {}
            # Iterate over column names and fetch unique values
            for column_name in column_names:
                query = f"SELECT DISTINCT `{column_name}` FROM `{table_name}`;"
                cursor.execute(query)
                results = cursor.fetchall()
                unique_values[column_name] = [row[0] for row in results]

            logger.info(f"Get Unique values for high cardinality columns - db utils in {time.time() - start_time} seconds.")
            return unique_values

    except Exception as e:
        logger.error(f"Exception in get_unique_values_for_columns: {str(e)}")
        return {}

async def upload_high_cardinality_columns(user_id, chatbot_id, high_cardinality_columns='', db_id: Optional[str] = None):
    try:
        db_id = db_id or await get_primary_db_id(chatbot_id)
        async for session in get_async_session():
            res = await session.execute(
                select(TableDescription).where(
                    TableDescription.user_id == user_id,
                    TableDescription.chatbot_id == chatbot_id,
                    TableDescription.db_id == db_id,
                )
            )
            record = res.scalars().first()
            if record:
                record.high_cardinality_columns = high_cardinality_columns or ''
            else:
                record = TableDescription(
                    user_id=user_id,
                    chatbot_id=chatbot_id,
                    db_id=db_id,
                    high_cardinality_columns=high_cardinality_columns or '',
                    created_at=datetime.utcnow()
                )
                session.add(record)
            await session.commit()
            return {"message": "upload_high_cardinality_columns function executed", "status": True}
    except Exception as e:
        logger.error(f"Exception in upload_high_cardinality_columns: {str(e)}")
        return {"message": f"Error in upload_high_cardinality_columns: {str(e)}", "status": False}

async def get_high_cardinality_columns(user_id, agent_id, db_id: Optional[str] = None):
    """
    Get high cardinality columns by agent_id.
    Queries by chatbot_id for backward compatibility.

    Args:
        user_id: User ID (can be None for new RESTful endpoints)
        agent_id: Agent ID
        db_id: Database ID (defaults to the agent's primary DB)
    """
    try:
        db_id = db_id or await get_primary_db_id(agent_id)
        async for session in get_async_session():
            # Build query - query chatbot_id column with agent_id value for backward compatibility
            query = select(TableDescription.high_cardinality_columns).where(
                TableDescription.chatbot_id == agent_id,
                TableDescription.db_id == db_id,
            )
            # Add user_id filter only if provided
            # if user_id:
            #     query = query.where(TableDescription.user_id == user_id)

            res = await session.execute(query)
            value = res.first()
            if value is not None:
                return {"record": {"high_cardinality_columns": value}, "message": "get_high_cardinality_columns function executed", "status": True}
            else:
                return {"record": None, "message": "get_high_cardinality_columns function executed: No Record Found", "status": False}
    except Exception as e:
        logger.error(f"Exception in get_high_cardinality_columns: {str(e)}")
        return {"message": f"Error in get_high_cardinality_columns: {str(e)}", "status": False}
