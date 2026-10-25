"""
Database utility functions for Column Descriptions
Similar to table_description_db_utils.py but for column-level descriptions
"""
import json
from datetime import datetime
from typing import Optional
from knowledge.services.logger import logger
from sqlmodel import select
from models.sql_models import ColumnDescription
from knowledge.services.sqlmodel_session import get_async_session
from agent.db_utils.database_db_utils import get_primary_db_id


async def upload_column_descriptions(user_id: str, agent_id: str, table_name: str, column_descriptions: dict, db_id: Optional[str] = None):
    """
    Upload or update column descriptions for a specific table by agent_id.

    Args:
        user_id: Optional user ID (not used for filtering, can be None)
        agent_id: Agent ID to query for
        table_name: Name of the table
        column_descriptions: Dictionary of column descriptions

    Returns:
        dict: Response with status and message
    """
    try:
        db_id = db_id or await get_primary_db_id(agent_id)
        async for session in get_async_session():
            # Query by agent_id and db_id
            res = await session.execute(
                select(ColumnDescription).where(
                    ColumnDescription.agent_id == agent_id,
                    ColumnDescription.db_id == db_id,
                    ColumnDescription.table_name == table_name
                )
            )
            record = res.scalars().first()

            if record:
                # Update existing record
                record.column_descriptions = dict(column_descriptions)
                record.updated_at = datetime.utcnow()
                if user_id:
                    record.user_id = user_id  # stamp the acting user on existing rows too
                # Mark the column as modified to ensure the change is persisted
                from sqlalchemy.orm import attributes
                attributes.flag_modified(record, "column_descriptions")
            else:
                # Create new record
                record = ColumnDescription(
                    user_id=user_id, # Can be None for master key
                    chatbot_id=agent_id, # Use agent_id for both fields
                    db_id=db_id,
                    agent_id=agent_id,
                    table_name=table_name,
                    column_descriptions=column_descriptions,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                session.add(record)

            await session.commit()
            await session.refresh(record)
            logger.info(f"Uploaded column descriptions for table {table_name}, agent_id={agent_id}")
            return {"message": "Column descriptions uploaded successfully", "status": True}
    except Exception as e:
        logger.error(f"Exception in upload_column_descriptions: {str(e)}")
        return {"message": f"Error in upload_column_descriptions: {str(e)}", "status": False}


async def get_column_descriptions(user_id: str, agent_id: str, table_name: str, db_id: Optional[str] = None):
    """
    Get column descriptions for a specific table by agent_id.

    Args:
        user_id: Optional user ID (not used for filtering, can be None)
        agent_id: Agent ID to query for
        table_name: Name of the table

    Returns:
        dict: {"status": bool, "record": dict or None, "message": str}
    """
    try:
        db_id = db_id or await get_primary_db_id(agent_id)
        async for session in get_async_session():
            # Query by agent_id and db_id
            res = await session.execute(
                select(ColumnDescription).where(
                    ColumnDescription.agent_id == agent_id,
                    ColumnDescription.db_id == db_id,
                    ColumnDescription.table_name == table_name
                )
            )
            record = res.scalars().first()

            if record:
                return {
                    "record": {
                        "table_name": record.table_name,
                        "column_descriptions": record.column_descriptions,
                        "created_at": record.created_at,
                        "updated_at": record.updated_at
                    },
                    "message": "Column descriptions retrieved successfully",
                    "status": True
                }
            else:
                return {
                    "record": None,
                    "message": "No column descriptions found for this table",
                    "status": False
                }
    except Exception as e:
        logger.error(f"Exception in get_column_descriptions: {str(e)}")
        return {"message": f"Error in get_column_descriptions: {str(e)}", "status": False}


async def get_all_column_descriptions(user_id: str, agent_id: str, db_id: Optional[str] = None):
    """
    Get column descriptions for all tables by agent_id.

    Args:
        user_id: Optional user ID (not used for filtering, can be None)
        agent_id: Agent ID to query for

    Returns:
        dict: Response with status, message, and records
    """
    try:
        db_id = db_id or await get_primary_db_id(agent_id)
        async for session in get_async_session():
            # Query by agent_id and db_id
            # agent_id OR chatbot_id: rows written before the agent_id column
            # existed carry only chatbot_id, and the table-description loader
            # already matches on both. Filtering on one hid rows from the other.
            from sqlalchemy import or_
            res = await session.execute(
                select(ColumnDescription).where(
                    or_(
                        ColumnDescription.agent_id == agent_id,
                        ColumnDescription.chatbot_id == agent_id,
                    ),
                    ColumnDescription.db_id == db_id,
                )
            )
            records = res.scalars().all()
            
            if records:
                records_list = [
                    {
                        "table_name": record.table_name,
                        "column_descriptions": record.column_descriptions,
                        "created_at": record.created_at,
                        "updated_at": record.updated_at
                    }
                    for record in records
                ]
                return {
                    "records": records_list,
                    "message": f"Found {len(records_list)} table(s) with column descriptions",
                    "status": True
                }
            else:
                return {
                    "records": [],
                    "message": "No column descriptions found",
                    "status": False
                }
    except Exception as e:
        logger.error(f"Exception in get_all_column_descriptions: {str(e)}")
        return {"message": f"Error in get_all_column_descriptions: {str(e)}", "status": False}


async def update_column_description(user_id: str, agent_id: str, table_name: str, column_name: str, description: str, db_id: Optional[str] = None):
    """
    Update description for a single column by agent_id.

    Args:
        user_id: Optional user ID (not used for filtering, can be None)
        agent_id: Agent ID to query for
        table_name: Name of the table
        column_name: Name of the column
        description: New description for the column

    Returns:
        dict: {"status": bool, "message": str}
    """
    try:
        db_id = db_id or await get_primary_db_id(agent_id)
        async for session in get_async_session():
            # Query by agent_id and db_id
            res = await session.execute(
                select(ColumnDescription).where(
                    ColumnDescription.agent_id == agent_id,
                    ColumnDescription.db_id == db_id,
                    ColumnDescription.table_name == table_name
                )
            )
            record = res.scalars().first()

            if record:
                # Update existing column description
                column_descriptions = record.column_descriptions or {}
                column_descriptions[column_name] = description
                # Force SQLAlchemy to detect the change by reassigning a new dict
                record.column_descriptions = dict(column_descriptions)
                record.updated_at = datetime.utcnow()
                # Mark the column as modified to ensure the change is persisted
                from sqlalchemy.orm import attributes
                attributes.flag_modified(record, "column_descriptions")
            else:
                # Create new record with single column description
                record = ColumnDescription(
                    user_id=user_id, # Can be None for master key
                    chatbot_id=agent_id, # Use agent_id for both fields
                    db_id=db_id,
                    agent_id=agent_id,
                    table_name=table_name,
                    column_descriptions={column_name: description},
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                session.add(record)
            
            await session.commit()
            return {"message": "Column description updated successfully", "status": True}
    except Exception as e:
        logger.error(f"Exception in update_column_description: {str(e)}")
        return {"message": f"Error in update_column_description: {str(e)}", "status": False}


async def delete_column_descriptions(user_id: str, agent_id: str, table_name: str, db_id: Optional[str] = None):
    """
    Delete all column descriptions for a specific table by agent_id.

    Args:
        user_id: Optional user ID (not used for filtering, can be None)
        agent_id: Agent ID to query for
        table_name: Name of the table

    Returns:
        dict: Response with status and message
    """
    try:
        db_id = db_id or await get_primary_db_id(agent_id)
        async for session in get_async_session():
            # Query by agent_id and db_id
            res = await session.execute(
                select(ColumnDescription).where(
                    ColumnDescription.agent_id == agent_id,
                    ColumnDescription.db_id == db_id,
                    ColumnDescription.table_name == table_name
                )
            )
            record = res.scalars().first()

            if record:
                await session.delete(record)
                await session.commit()
                logger.info(f"Deleted column descriptions for table {table_name}, agent_id={agent_id}")
                return {"message": "Column descriptions deleted successfully", "status": True}
            else:
                return {"message": "No column descriptions found to delete", "status": False}
    except Exception as e:
        logger.error(f"Exception in delete_column_descriptions: {str(e)}")
        return {"message": f"Error in delete_column_descriptions: {str(e)}", "status": False}


async def delete_single_column_description(user_id: str, agent_id: str, table_name: str, column_name: str, db_id: Optional[str] = None):
    """
    Delete description for a single column by agent_id.

    Args:
        user_id: Optional user ID (not used for filtering, can be None)
        agent_id: Agent ID to query for
        table_name: Name of the table
        column_name: Name of the column to delete

    Returns:
        dict: Response with status and message
    """
    try:
        db_id = db_id or await get_primary_db_id(agent_id)
        async for session in get_async_session():
            # Query by agent_id and db_id
            res = await session.execute(
                select(ColumnDescription).where(
                    ColumnDescription.agent_id == agent_id,
                    ColumnDescription.db_id == db_id,
                    ColumnDescription.table_name == table_name
                )
            )
            record = res.scalars().first()

            if record and record.column_descriptions:
                column_descriptions = record.column_descriptions
                if column_name in column_descriptions:
                    del column_descriptions[column_name]
                    record.column_descriptions = column_descriptions
                    record.updated_at = datetime.utcnow()
                    await session.commit()
                    logger.info(f"Deleted column description for {column_name} in table {table_name}, agent_id={agent_id}")
                    return {"message": "Column description deleted successfully", "status": True}
                else:
                    return {"message": f"Column {column_name} not found in descriptions", "status": False}
            else:
                return {"message": "No column descriptions found for this table", "status": False}
    except Exception as e:
        logger.error(f"Exception in delete_single_column_description: {str(e)}")
        return {"message": f"Error in delete_single_column_description: {str(e)}", "status": False}

