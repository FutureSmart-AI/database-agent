import time
from datetime import datetime, timedelta

from agent.db_utils.common_db_utils import get_connection
from agent.db_utils.common_postresql_utils import execute_sql_query, db_rows_affected_log
from logger import logger
from sqlmodel import select
from models.sql_models import FewShotExamples
from agent.services.sqlmodel_session import get_async_session
from typing import Optional
from agent.db_utils.database_db_utils import get_primary_db_id

async def upload_to_db_few_shot(user_id, agent_id, few_shot_examples, file_name='', db_id: Optional[str] = None):
    """
    Upload few-shot examples by agent_id.
    Queries by agent_id OR chatbot_id for backward compatibility.

    Args:
        user_id: User ID (can be None for new RESTful endpoints)
        agent_id: Agent ID
        few_shot_examples: Few-shot examples to upload
        file_name: Optional file name
        db_id: Database ID (defaults to the agent's primary DB)
    """
    try:
        from sqlalchemy import or_
        db_id = db_id or await get_primary_db_id(agent_id)
        async for session in get_async_session():
            # Query by agent_id OR chatbot_id for backward compatibility
            query = select(FewShotExamples).where(
                or_(
                    FewShotExamples.agent_id == agent_id,
                    FewShotExamples.chatbot_id == agent_id
                ),
                FewShotExamples.db_id == db_id
            )
            # Match on (agent/chatbot_id, db_id) only — that pair is the PK, so a user_id
            # filter here could only mis-match the single row and force a PK-conflicting insert.
            res = await session.execute(query)
            record = res.first()
            if record:
                record = record[0]  # Unpack ORM object from tuple
                record.file_name = file_name
                record.few_shot_examples = few_shot_examples
                # Update both IDs for consistency
                record.agent_id = agent_id
                record.chatbot_id = agent_id
                record.db_id = db_id
                record.updated_at = datetime.utcnow()
                if user_id:
                    record.updated_by = user_id  # acting dashboard user on this edit
                    if not record.user_id:
                        record.user_id = user_id  # adopt as creator if it was never recorded
            else:
                record = FewShotExamples(
                    user_id=user_id,
                    chatbot_id=agent_id,
                    agent_id=agent_id,  # Sync both IDs for consistency
                    db_id=db_id,
                    file_name=file_name,
                    few_shot_examples=few_shot_examples
                )
                session.add(record)
            await session.commit()
            return {"message": "Few-shot examples uploaded successfully", "status": True}
    except Exception as e:
        logger.error(f"Exception in upload_to_db_few_shot: {str(e)}")
        return {"message": f"Error in upload_to_db_few_shot: {str(e)}", "status": False}

async def list_fewshot_examples_from_db(user_id: str, agent_id: str, db_id: Optional[str] = None):
    """
    List few-shot examples by agent_id.
    Queries by agent_id OR chatbot_id for backward compatibility.

    Args:
        user_id: User ID (can be None for new RESTful endpoints)
        agent_id: Agent ID
        db_id: Database ID (defaults to the agent's primary DB)
    """
    try:
        from sqlalchemy import or_
        db_id = db_id or await get_primary_db_id(agent_id)
        async for session in get_async_session():
            # Query by agent_id OR chatbot_id for backward compatibility
            query = select(FewShotExamples.few_shot_examples, FewShotExamples.created_at, FewShotExamples.db_id).where(
                or_(
                    FewShotExamples.agent_id == agent_id,
                    FewShotExamples.chatbot_id == agent_id
                ),
                FewShotExamples.db_id == db_id
            )
            # Add user_id filter only if provided
            if user_id:
                query = query.where(FewShotExamples.user_id == user_id)

            res = await session.execute(query)
            record = res.first()
            if record:
                return {"record": {"few_shot_examples": record[0], "created_at": record[1], "db_id": record[2]}, "message": "Few-shot examples listed successfully", "status": True}
            else:
                return {"record": None, "message": "No few-shot examples found", "status": False}
    except Exception as e:
        logger.error(f"Exception in list_fewshot_examples_from_db: {str(e)}")
        return {"message": f"Error in list_fewshot_examples_from_db: {str(e)}", "status": False}

async def update_fewshot_examples(user_id: str, agent_id: str, few_shot_examples: str, db_id: Optional[str] = None):
    """
    Update few-shot examples by agent_id.
    Queries by agent_id OR chatbot_id for backward compatibility.
    """
    try:
        from sqlalchemy import or_
        db_id = db_id or await get_primary_db_id(agent_id)
        async for session in get_async_session():
            query = select(FewShotExamples).where(
                or_(
                    FewShotExamples.agent_id == agent_id,
                    FewShotExamples.chatbot_id == agent_id
                ),
                FewShotExamples.db_id == db_id
            )
            res = await session.execute(query)
            record = res.first()
            if not record:
                return {"message": "No few-shot examples found", "status": False}
            record = record[0]  # Unpack ORM object from tuple
            record.few_shot_examples = few_shot_examples
            record.agent_id = agent_id
            record.chatbot_id = agent_id
            record.db_id = db_id
            record.updated_at = datetime.utcnow()
            if user_id:
                record.updated_by = user_id  # acting dashboard user on this edit
                if not record.user_id:
                    record.user_id = user_id  # adopt as creator if it was never recorded
            await session.commit()
            return {"message": "Few-shot examples updated successfully", "status": True}
    except Exception as e:
        logger.error(f"Exception in update_fewshot_examples: {str(e)}")
        return {"message": f"Error in update_fewshot_examples: {str(e)}", "status": False}

async def delete_fewshot_examples_db(user_id, agent_id, nl_query, db_id: Optional[str] = None):
    """
    Delete few-shot examples by agent_id.
    Queries by agent_id OR chatbot_id for backward compatibility.
    """
    try:
        from sqlalchemy import or_
        db_id = db_id or await get_primary_db_id(agent_id)
        async for session in get_async_session():
            query = select(FewShotExamples).where(
                or_(
                    FewShotExamples.agent_id == agent_id,
                    FewShotExamples.chatbot_id == agent_id
                ),
                FewShotExamples.db_id == db_id
            )
            res = await session.execute(query)
            record = res.first()
            if not record:
                return {"message": "No few-shot examples found", "status": False}
            record = record[0]  # Unpack ORM object from tuple
            await session.delete(record)
            await session.commit()
            return {"message": "Few-shot examples deleted successfully", "status": True}
    except Exception as e:
        logger.error(f"Exception in delete_fewshot_examples_db: {str(e)}")
        return {"message": f"Error in delete_fewshot_examples_db: {str(e)}", "status": False}
            