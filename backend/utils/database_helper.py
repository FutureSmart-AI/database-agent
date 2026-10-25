from typing import Optional, Dict, Any
from fastapi import HTTPException
from logger import logger
from database_connection.db_utils.database_db_utils import (
    get_db_connection_by_agent_id,
    upsert_db_connection_in_db,
    test_db_connection
)
from database_connection.db_utils.table_description_db_utils import (
    upload_to_db_table_description,
    list_table_description_from_db
)
from chatbot_management.db_utils.chatbot_params_db_utils import get_chatbot_details_by_agent_id
from database_connection.utils.common_utils import validate_database_request
from database_connection.utils.exceptions import DatabaseConnectionError

async def get_agent_database_connection(agent_id: str) -> Dict[str, Any]:
    """
    Get database connection details for an agent
    """
    # Verify agent exists
    agent = await get_chatbot_details_by_agent_id(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    # Get database connection
    connection = await get_db_connection_by_agent_id(agent_id)

    if not connection:
        return {"message": f"Database connection doesn't exist for agent_id {agent_id}"}

    return {
        "db_host": connection.db_host,
        "db_name": connection.db_name,
        "db_user": connection.db_user,
        "db_password": connection.db_password,
        "db_port": connection.db_port,
        "db_engine": connection.db_engine
    }

async def update_agent_database_connection(agent_id: str, body: Any) -> Dict[str, Any]:
    """
    Update database connection for an agent
    """
    # Verify agent exists
    agent = await get_chatbot_details_by_agent_id(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    # Validate input
    is_valid, error_msg = validate_database_request(
        engine=body.db_engine,
        host=body.db_host,
        db_name=body.db_name,
        port=body.db_port
    )
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)

    # Test the connection
    try:
        connection_test = await test_db_connection(
            host=body.db_host,
            user=body.db_user,
            password=body.db_password,
            db=body.db_name,
            port=body.db_port,
            db_engine=body.db_engine
        )
        if not connection_test.get("status"):
            test_error = connection_test.get("message", "Connection test failed")
            raise HTTPException(status_code=400, detail=test_error)
    except DatabaseConnectionError as e:
        logger.error(f"Database connection test failed: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))

    # Get owner_id for database constraint compatibility
    owner_id = agent.owner_id if agent.owner_id else "unknown"

    # Upsert connection
    db_details = {
        "db_host": body.db_host,
        "db_name": body.db_name,
        "db_user": body.db_user,
        "db_password": body.db_password,
        "db_port": body.db_port,
        "db_engine": body.db_engine
    }
    
    await upsert_db_connection_in_db(agent_id, db_details, owner_id, owner_id=agent.owner_id)

    # Initialize empty table description if it doesn't exist
    try:
        db_desc = await list_table_description_from_db(None, agent_id)
        if not (db_desc and db_desc.get("status")):
            logger.info(f"Uploading empty table description for {agent_id}")
            await upload_to_db_table_description(None, agent_id, file_name='', url='', description='[]', entry_flags='{}')
    except Exception as e:
        logger.error(f"Error while uploading empty table description: {str(e)}")

    return {
        "message": f"Database connection updated successfully for {agent_id}"
    }

async def test_raw_database_connection(body: Any) -> Dict[str, Any]:
    """
    Test a database connection without associating it with an agent
    """
    # Validate input
    is_valid, error_msg = validate_database_request(
        engine=body.db_engine,
        host=body.db_host,
        db_name=body.db_name,
        port=body.db_port
    )
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)

    # Test the connection
    try:
        connection = await test_db_connection(
            host=body.db_host,
            user=body.db_user,
            password=body.db_password,
            db=body.db_name,
            port=body.db_port,
            db_engine=body.db_engine
        )
        return {"message": connection["message"]}
    except DatabaseConnectionError as e:
        logger.error(f"Database connection error: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"An error occurred during connection test: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal Server Error")
