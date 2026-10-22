from typing import Optional, Dict, Any
from fastapi import HTTPException
from chatbot_management.services.logger import logger
from database_connection.db_utils.table_description_db_utils import (
    upload_to_db_table_description,
    list_table_description_from_db
)
from database_connection.utils.common_utils import validate_database_request
from database_connection.utils.exceptions import DatabaseConnectionError


async def get_agent_database_connection(agent_id: str) -> Dict[str, Any]:
    """Get database connection details for an agent"""
    from chatbot_management.services.sqlmodel_session import get_async_session
    from models.sql_models import ChatbotConnection, ChatbotDetails
    from sqlmodel import select

    async for session in get_async_session():
        agent_result = await session.execute(
            select(ChatbotDetails).where(ChatbotDetails.agent_id == agent_id)
        )
        agent = agent_result.scalar_one_or_none()
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

        # Multi-DB: an agent can have many connections — return the PRIMARY (legacy view).
        connection_result = await session.execute(
            select(ChatbotConnection)
            .where(
                ChatbotConnection.agent_id == agent_id,
                ChatbotConnection.deleted == False,  # noqa: E712 — never surface a detached DB
            )
            .order_by(ChatbotConnection.is_active.desc(), ChatbotConnection.created_at)
        )
        connection = connection_result.scalars().first()

        if not connection:
            return {"message": f"Database connection doesn't exist for agent_id {agent_id}"}

        return {
            "db_id": connection.db_id,
            "db_host": connection.db_host,
            "db_name": connection.db_name,
            "db_user": connection.db_user,
            "db_password": connection.db_password,
            "db_port": connection.db_port,
            "db_engine": connection.db_engine
        }


async def update_agent_database_connection(agent_id: str, body: Any) -> Dict[str, Any]:
    """Update database connection. Returns result including whether DB identity changed."""
    from chatbot_management.services.sqlmodel_session import get_async_session
    from models.sql_models import ChatbotConnection, ChatbotDetails
    from sqlmodel import select
    from database_connection.db_utils.database_db_utils import test_db_connection

    async for session in get_async_session():
        # Verify agent
        agent_result = await session.execute(
            select(ChatbotDetails).where(ChatbotDetails.agent_id == agent_id)
        )
        agent = agent_result.scalar_one_or_none()
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

        # Validate input
        is_valid, error_msg = validate_database_request(
            engine=body.db_engine, host=body.db_host, db_name=body.db_name, port=body.db_port
        )
        if not is_valid:
            raise HTTPException(status_code=400, detail=error_msg)

        owner_id = agent.owner_id if agent.owner_id else "unknown"

        # Test connection
        try:
            connection_test = await test_db_connection(
                host=body.db_host, user=body.db_user, password=body.db_password,
                db=body.db_name, port=body.db_port, db_engine=body.db_engine
            )
            if not connection_test.get("status"):
                raise HTTPException(status_code=400, detail=connection_test.get("message", "Connection test failed"))
        except DatabaseConnectionError as e:
            raise HTTPException(status_code=400, detail=str(e))

        # Get existing for change detection — target the PRIMARY connection (legacy path).
        conn_result = await session.execute(
            select(ChatbotConnection)
            .where(
                ChatbotConnection.agent_id == agent_id,
                ChatbotConnection.deleted == False,  # noqa: E712 — never edit a detached DB
            )
            .order_by(ChatbotConnection.is_active.desc(), ChatbotConnection.created_at)
        )
        connection = conn_result.scalars().first()

        prev_host = connection.db_host if connection else None
        prev_name = connection.db_name if connection else None
        prev_port = connection.db_port if connection else None
        prev_engine = connection.db_engine if connection else None

        if connection:
            connection.db_host = body.db_host
            connection.db_name = body.db_name
            connection.db_user = body.db_user
            connection.db_password = body.db_password
            connection.db_port = body.db_port
            connection.db_engine = body.db_engine
            if not connection.agent_id:
                connection.agent_id = agent_id
        else:
            # Multi-DB: a brand-new legacy connection becomes the agent's primary DB.
            from agent.db_utils.database_db_utils import generate_db_id
            connection = ChatbotConnection(
                db_id=generate_db_id(), user_id=owner_id, owner_id=owner_id,
                chatbot_id=agent_id, agent_id=agent_id,
                db_host=body.db_host, db_name=body.db_name, db_user=body.db_user,
                db_password=body.db_password, db_port=body.db_port, db_engine=body.db_engine,
                is_active=True, status="connected",
            )
            session.add(connection)

        await session.commit()
        await session.refresh(connection)

    db_changed = (
        prev_host is None
        or prev_host != body.db_host
        or prev_name != body.db_name
        or str(prev_port) != str(body.db_port)
        or prev_engine != body.db_engine
    )

    # Init empty table description if not exists
    try:
        db_desc = await list_table_description_from_db(None, agent_id)
        if not (db_desc and db_desc.get("status")):
            await upload_to_db_table_description(None, agent_id, file_name='', url='', description='[]', entry_flags='{}')
    except Exception as e:
        logger.error(f"Error initializing table description: {str(e)}")

    return {
        "message": f"Database connection updated successfully for {agent_id}",
        "db_changed": db_changed,
        "owner_id": owner_id
    }


async def test_raw_database_connection(body: Any) -> Dict[str, Any]:
    """Test a database connection without associating it with an agent"""
    from database_connection.db_utils.database_db_utils import test_db_connection

    # Validate input
    is_valid, error_msg = validate_database_request(
        engine=body.db_engine, host=body.db_host, db_name=body.db_name, port=body.db_port
    )
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)

    try:
        connection = await test_db_connection(
            host=body.db_host, user=body.db_user, password=body.db_password,
            db=body.db_name, port=body.db_port, db_engine=body.db_engine
        )
        return {"message": connection["message"]}
    except DatabaseConnectionError as e:
        logger.error(f"Database connection error: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"An error occurred during connection test: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal Server Error")
