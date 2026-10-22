import time
import json
from agent.utils.table_flag_writes import canonical_table_flags_for_write
from datetime import datetime, timedelta
from typing import Optional
import pymysql
import psycopg2
from knowledge.services.logger import logger
from sqlmodel import select
from models.sql_models import TableDescription
from knowledge.services.sqlmodel_session import get_async_session
from agent.db_utils.database_db_utils import get_primary_db_id

async def upload_to_db_table_description(user_id, agent_id, file_name='', url='', description='', entry_flags='', db_id: Optional[str] = None):
    """
    Upload table descriptions by agent_id.

    Args:
        user_id: Optional user ID (not used for filtering, can be None)
        agent_id: Agent ID to query for
        file_name: Optional filename
        url: Optional URL
        description: Table descriptions (JSON string or dict)
        entry_flags: Entry flags (JSON string or dict)

    Returns:
        dict: Response with status and message
    """
    try:
        entry_flags = canonical_table_flags_for_write(entry_flags)
        db_id = db_id or await get_primary_db_id(agent_id)
        async for session in get_async_session():
            # Query by agent_id and db_id
            res = await session.execute(
                select(TableDescription).where(
                    TableDescription.agent_id == agent_id,
                    TableDescription.db_id == db_id,
                )
            )
            record = res.scalars().first()

            if record:
                # Handle description conversion if it's a string
                if isinstance(description, str):
                    try:
                        description = json.loads(description)
                    except json.JSONDecodeError:
                        logger.warning("Description is not valid JSON, storing as is")

                # Handle entry_flags conversion if it's a string
                if isinstance(entry_flags, str):
                    try:
                        entry_flags = json.loads(entry_flags)
                    except json.JSONDecodeError:
                        logger.warning("Entry flags is not valid JSON, storing as is")

                record.file_name = file_name
                record.url = url
                record.description = description
                record.entry_flags = entry_flags
                record.updated_at = datetime.utcnow()
                if user_id:
                    record.updated_by = user_id  # acting dashboard user on this edit
                    if not record.user_id:
                        record.user_id = user_id  # adopt as creator if it was never recorded
            else:
                record = TableDescription(
                    user_id=user_id,
                    chatbot_id=agent_id,  # Use agent_id for both fields
                    db_id=db_id,
                    agent_id=agent_id,
                    file_name=file_name,
                    url=url,
                    description=description,
                    entry_flags=entry_flags,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                session.add(record)
            await session.commit()
            await session.refresh(record)
            logger.info(f"Uploaded table descriptions for agent_id={agent_id}")
            return {"message": "upload_to_db_table_description function executed", "status": True}
    except Exception as e:
        logger.error(f"Exception in upload_to_db_table_description: {str(e)}")
        return {"message": f"Error in upload_to_db_table_description: {str(e)}", "status": False}

async def update_table_description(user_id, agent_id, file_name='', description='', db_id: Optional[str] = None):
    """
    Update table descriptions by agent_id.

    Args:
        user_id: Optional user ID (not used for filtering, can be None)
        agent_id: Agent ID to query for
        file_name: Optional filename
        description: Table descriptions (JSON string or dict)

    Returns:
        dict: Response with status and message
    """
    try:
        db_id = db_id or await get_primary_db_id(agent_id)
        async for session in get_async_session():
            # Query by agent_id and db_id
            res = await session.execute(
                select(TableDescription).where(
                    TableDescription.agent_id == agent_id,
                    TableDescription.db_id == db_id,
                )
            )
            record = res.scalars().first()

            if record:
                # Handle description conversion if it's a string
                if isinstance(description, str):
                    try:
                        description = json.loads(description)
                    except json.JSONDecodeError:
                        logger.warning("Description is not valid JSON, storing as is")

                record.file_name = file_name
                record.description = description
                record.updated_at = datetime.utcnow()
                if user_id:
                    record.updated_by = user_id  # acting dashboard user on this edit
                    if not record.user_id:
                        record.user_id = user_id  # adopt as creator if it was never recorded
                await session.commit()
                await session.refresh(record)
                logger.info(f"Updated table descriptions for agent_id={agent_id}")
                return {"message": "update_table_description function executed", "status": True}
            else:
                logger.warning(f"No table descriptions found for agent_id={agent_id}")
                return {"message": "update_table_description function executed: No Record Found", "status": False}
    except Exception as e:
        logger.error(f"Exception in update_table_description: {str(e)}")
        return {"message": f"Error in update_table_description: {str(e)}", "status": False}

async def list_table_description_from_db(user_id: str, agent_id: str, db_id: Optional[str] = None):
    """
    Get table descriptions by agent_id.

    Args:
        user_id: Optional user ID (not used for filtering, can be None)
        agent_id: Agent ID to query for

    Returns:
        dict: Response with status, message, and record
    """
    try:
        db_id = db_id or await get_primary_db_id(agent_id)
        async for session in get_async_session():
            # Query by agent_id and db_id
            res = await session.execute(
                select(TableDescription).where(
                    TableDescription.agent_id == agent_id,
                    TableDescription.db_id == db_id,
                )
            )
            record = res.scalars().first()

            if record:
                logger.info(f"Found table descriptions for agent_id={agent_id}")
                return {"record": record, "message": "list_table_description_from_db function executed", "status": True}
            else:
                logger.info(f"No table descriptions found for agent_id={agent_id}")
                return {"record": None, "message": "list_table_description_from_db function executed: No Record Found", "status": False}
    except Exception as e:
        logger.error(f"Exception in list_table_description_from_db: {str(e)}")
        return {"message": f"Error in list_table_description_from_db: {str(e)}", "status": False}

async def get_include_exclude_table_names(user_id, agent_id, db_id: Optional[str] = None):
    """
    Get include/exclude table names by agent_id.

    Args:
        user_id: Optional user ID (not used for filtering, can be None)
        agent_id: Agent ID to query for

    Returns:
        dict: Response with status, message, and entry_flags
    """
    try:
        db_id = db_id or await get_primary_db_id(agent_id)
        async for session in get_async_session():
            # Query by agent_id and db_id
            result = await session.execute(
                select(TableDescription.entry_flags).where(
                    TableDescription.agent_id == agent_id,
                    TableDescription.db_id == db_id,
                )
            )
            record = result.first()
            if record is not None:
                return {"record": {"entry_flags": record[0]}, "message": "get_include_exclude_table_names function executed", "status": True}
            else:
                return {"record": None, "message": "get_include_exclude_table_names function executed: No Record Found", "status": False}
    except Exception as e:
        logger.error(f"Exception in get_include_exclude_table_names: {str(e)}")
        return {"message": f"Error in get_include_exclude_table_names: {str(e)}", "status": False}

async def upload_to_db_include_or_exclude_table_names(user_id, agent_id, entry_flags, db_id: Optional[str] = None):
    """
    Upload include/exclude table names by agent_id.

    Args:
        user_id: Optional user ID (not used for filtering, can be None)
        agent_id: Agent ID to query for
        entry_flags: Entry flags (JSON string or dict)

    Returns:
        dict: Response with status and message
    """
    try:
        entry_flags = canonical_table_flags_for_write(entry_flags)
        db_id = db_id or await get_primary_db_id(agent_id)
        async for session in get_async_session():
            # Query by agent_id and db_id
            res = await session.execute(
                select(TableDescription).where(
                    TableDescription.agent_id == agent_id,
                    TableDescription.db_id == db_id,
                )
            )
            record = res.first()
            if record:
                record = record[0]  # Unpack ORM object from tuple
                record.entry_flags = entry_flags
                record.updated_at = datetime.utcnow()
                if user_id:
                    record.updated_by = user_id  # acting dashboard user on this edit
                    if not record.user_id:
                        record.user_id = user_id  # adopt as creator if it was never recorded
            else:
                record = TableDescription(
                    user_id=user_id,
                    chatbot_id=agent_id,  # Use agent_id for both fields
                    db_id=db_id,
                    agent_id=agent_id,
                    entry_flags=entry_flags,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                session.add(record)
            await session.commit()
            await session.refresh(record)
            logger.info(f"Uploaded entry_flags for agent_id={agent_id}")
            return {"message": "upload_to_db_include_or_exclude_table_names function executed", "status": True}
    except Exception as e:
        logger.error(f"Exception in upload_to_db_include_or_exclude_table_names: {str(e)}")
        return {"message": f"Error in upload_to_db_include_or_exclude_table_names: {str(e)}", "status": False}

async def delete_table_descriptions_db(user_id, agent_id, description, db_id: Optional[str] = None):
    """
    Delete table descriptions by agent_id.

    Args:
        user_id: Optional user ID (not used for filtering, can be None)
        agent_id: Agent ID to query for
        description: New description value

    Returns:
        dict: Response with status and message
    """
    try:
        db_id = db_id or await get_primary_db_id(agent_id)
        async for session in get_async_session():
            # Query by agent_id and db_id
            res = await session.execute(
                select(TableDescription).where(
                    TableDescription.agent_id == agent_id,
                    TableDescription.db_id == db_id,
                )
            )
            record = res.first()
            if not record:
                return {"message": "delete_table_descriptions_db function executed: No Record Found", "status": False}
            record = record[0]  # Unpack ORM object from tuple
            record.description = description
            now = datetime.utcnow()
            record.updated_at = now
            # The row survives a delete here — deleting table descriptions clears the
            # description payload rather than removing the row — so the delete audit
            # lands on the surviving row.
            record.deleted_at = now
            if user_id:
                record.updated_by = user_id  # acting dashboard user on this edit
                record.deleted_by = user_id  # ...who performed the delete
                if not record.user_id:
                    record.user_id = user_id  # adopt as creator if it was never recorded
            await session.commit()
            return {"message": "delete_table_descriptions_db function executed", "status": True}
    except Exception as e:
        logger.error(f"Exception in delete_table_descriptions_db: {str(e)}")
        return {"message": f"Error in delete_table_descriptions_db: {str(e)}", "status": False}

def get_db_connection(db_details):
    d = db_details['db_details']
    engine = (d.get('db_engine') or '').lower()  # case-insensitive: accepts "PostgreSQL" etc.
    if engine == 'mysql':
        return pymysql.connect(
            host=d['db_host'], user=d['db_user'], password=d['db_password'],
            database=d['db_name'], port=int(d.get('db_port') or 3306),
        )
    elif engine == 'postgresql':
        return psycopg2.connect(
            host=d['db_host'], user=d['db_user'], password=d['db_password'],
            database=d['db_name'], port=int(d.get('db_port') or 5432),
        )
    raise ValueError(f"Unsupported db_engine: {d.get('db_engine')!r}")

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
        
        logger.info("Table dbutils - get_unique_values_for_columns")
        connection = get_db_connection(db_details)
        
        try:
            # Detect DB engine
            db_engine = db_details.get('db_details', {}).get('db_engine', 'mysql').lower()
            
            with connection.cursor() as cursor:
                unique_values = {}
                for column_name in column_names:
                    # Use correct quoting based on DB engine
                    if db_engine == 'postgresql':
                        query = f'SELECT DISTINCT "{column_name}" FROM "{table_name}";'
                    else:
                        query = f"SELECT DISTINCT `{column_name}` FROM `{table_name}`;"
                    
                    cursor.execute(query)
                    results = cursor.fetchall()
                    unique_values[column_name] = [str(row[0]) for row in results if row[0] is not None]

                logger.info(f"Get Unique values for high cardinality columns - db utils in {time.time() - start_time} seconds.")
                return unique_values
        finally:
            connection.close()

    except Exception as e:
        logger.error(f"Exception in get_unique_values_for_columns: {str(e)}")
        return {}

async def upload_high_cardinality_columns(user_id, agent_id, high_cardinality_columns='', db_id: Optional[str] = None):
    """
    Upload high cardinality columns by agent_id.

    Args:
        user_id: Optional user ID (not used for filtering, can be None)
        agent_id: Agent ID to query for
        high_cardinality_columns: High cardinality columns (JSON string or dict)

    Returns:
        dict: Response with status and message
    """
    try:
        # Ensure we store only JSON-serializable data
        if not isinstance(high_cardinality_columns, str):
            import json
            high_cardinality_columns = json.dumps(high_cardinality_columns)
        db_id = db_id or await get_primary_db_id(agent_id)
        async for session in get_async_session():
            # Query by agent_id and db_id
            res = await session.execute(
                select(TableDescription).where(
                    TableDescription.agent_id == agent_id,
                    TableDescription.db_id == db_id,
                )
            )
            record = res.scalars().first()
            if record:
                record.high_cardinality_columns = high_cardinality_columns or ''
                record.updated_at = datetime.utcnow()
            else:
                record = TableDescription(
                    user_id=user_id,
                    chatbot_id=agent_id,  # Use agent_id for both fields
                    db_id=db_id,
                    agent_id=agent_id,
                    high_cardinality_columns=high_cardinality_columns or '',
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                session.add(record)
            await session.commit()
            await session.refresh(record)
            logger.info(f"Uploaded high_cardinality_columns for agent_id={agent_id}")
            return {"message": "upload_high_cardinality_columns function executed", "status": True}
    except Exception as e:
        logger.error(f"Exception in upload_high_cardinality_columns: {str(e)}")
        return {"message": f"Error in upload_high_cardinality_columns: {str(e)}", "status": False}

async def get_high_cardinality_columns(user_id, agent_id, db_id: Optional[str] = None):
    """
    Get high cardinality columns by agent_id.

    Args:
        user_id: Optional user ID (not used for filtering, can be None)
        agent_id: Agent ID to query for

    Returns:
        dict: Response with status, message, and high_cardinality_columns
    """
    try:
        db_id = db_id or await get_primary_db_id(agent_id)
        async for session in get_async_session():
            # Query by agent_id and db_id
            res = await session.execute(
                select(TableDescription.high_cardinality_columns).where(
                    TableDescription.agent_id == agent_id,
                    TableDescription.db_id == db_id,
                )
            )
            value = res.first()
            if value is not None:
                # value is a tuple like (json_data,)
                return {"record": value[0], "message": "get_high_cardinality_columns function executed", "status": True}
            else:
                return {"record": None, "message": "get_high_cardinality_columns function executed: No Record Found", "status": False}
    except Exception as e:
        logger.error(f"Exception in get_high_cardinality_columns: {str(e)}")
        return {"message": f"Error in get_high_cardinality_columns: {str(e)}", "status": False}
