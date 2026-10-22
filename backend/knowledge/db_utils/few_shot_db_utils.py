import time
from datetime import datetime, timedelta

from knowledge.services.logger import logger
from sqlmodel import select
from models.sql_models import FewShotExamples
from knowledge.services.sqlmodel_session import get_async_session
from typing import Optional
from agent.db_utils.database_db_utils import get_primary_db_id

async def upload_to_db_few_shot(user_id, agent_id, few_shot_examples, file_name='', db_id: Optional[str] = None):
    """
    Upload few-shot examples by agent_id.

    Args:
        user_id: User ID (optional, can be None)
        agent_id: Agent ID (primary identifier)
        few_shot_examples: Few-shot examples to upload
        file_name: Optional file name
        db_id: Database ID (defaults to the agent's primary DB)
    """
    try:
        db_id = db_id or await get_primary_db_id(agent_id)
        async for session in get_async_session():
            res = await session.execute(
                select(FewShotExamples).where(
                    FewShotExamples.agent_id == agent_id,
                    FewShotExamples.db_id == db_id
                )
            )
            record = res.first()
            # Normalize incoming examples to list[dict]
            try:
                new_list = []
                if isinstance(few_shot_examples, str):
                    parsed = few_shot_examples.strip()
                    if parsed:
                        parsed_json = None
                        try:
                            parsed_json = __import__('json').loads(parsed)
                        except Exception:
                            parsed_json = []
                        if isinstance(parsed_json, list):
                            new_list = parsed_json
                        elif isinstance(parsed_json, dict) and parsed_json.get("few_shot_examples"):
                            new_list = parsed_json.get("few_shot_examples") or []
                        else:
                            new_list = []
                    else:
                        new_list = []
                elif isinstance(few_shot_examples, list):
                    new_list = few_shot_examples
                else:
                    new_list = []
            except Exception as e:
                logger.error(f"upload_to_db_few_shot: error parsing incoming examples: {e}")
                new_list = []

            def _norm(s: str) -> str:
                return " ".join((s or "").strip().split()).lower()

            if record:
                # Merge with existing instead of overwriting
                db_obj = record[0]
                existing_raw = db_obj.few_shot_examples
                existing_list = []
                try:
                    if isinstance(existing_raw, str) and existing_raw:
                        existing_list = __import__('json').loads(existing_raw)
                    elif isinstance(existing_raw, list):
                        existing_list = existing_raw
                except Exception as e:
                    logger.error(f"upload_to_db_few_shot: error parsing existing examples: {e}")
                    existing_list = []

                merged: dict[str, str] = {}
                existing_norm = set()
                for item in existing_list:
                    if isinstance(item, dict):
                        for k, v in item.items():
                            merged[k] = v
                            existing_norm.add(_norm(k))
                added = 0
                for item in new_list:
                    if isinstance(item, dict):
                        for k, v in item.items():
                            kn = _norm(k)
                            if kn not in existing_norm:
                                merged[k] = v
                                existing_norm.add(kn)
                                added += 1
                final_list = [{k: v} for k, v in merged.items()]
                db_obj.file_name = file_name
                db_obj.few_shot_examples = __import__('json').dumps(final_list)
                db_obj.updated_at = datetime.utcnow()
                if user_id:
                    db_obj.updated_by = user_id  # acting dashboard user on this edit
                    if not db_obj.user_id:
                        db_obj.user_id = user_id  # adopt as creator if it was never recorded
                await session.commit()
                return {"message": "Few-shot examples merged successfully", "status": True, "added": added, "total": len(final_list)}
            else:
                # Create new with provided list
                final_payload = few_shot_examples
                if not isinstance(few_shot_examples, str):
                    final_payload = __import__('json').dumps(new_list)
                db_obj = FewShotExamples(
                    user_id=user_id,
                    chatbot_id=agent_id,  # Sync both IDs for consistency
                    agent_id=agent_id,
                    db_id=db_id,
                    file_name=file_name,
                    few_shot_examples=final_payload,
                    updated_at=datetime.utcnow()
                )
                session.add(db_obj)
                await session.commit()
                return {"message": "Few-shot examples uploaded successfully", "status": True, "added": len(new_list), "total": len(new_list)}
    except Exception as e:
        logger.error(f"Exception in upload_to_db_few_shot: {str(e)}")
        return {"message": f"Error in upload_to_db_few_shot: {str(e)}", "status": False}

async def list_fewshot_examples_from_db(user_id: str = None, agent_id: str = None, db_id: Optional[str] = None):
    """
    List few-shot examples by agent_id.

    Args:
        user_id: User ID (optional, for backward compatibility)
        agent_id: Agent ID (primary identifier)
        db_id: Database ID (defaults to the agent's primary DB)
    """
    try:
        db_id = db_id or await get_primary_db_id(agent_id)
        async for session in get_async_session():
            query = select(FewShotExamples)
            if agent_id:
                query = query.where(FewShotExamples.agent_id == agent_id)
            query = query.where(FewShotExamples.db_id == db_id)

            result = await session.execute(query)
            examples = result.scalars().all()
            
            if examples:
                # Convert SQLModel objects to dictionaries
                examples_dict = [
                    {
                        "agent_id": ex.agent_id,
                        "chatbot_id": ex.chatbot_id,
                        "db_id": ex.db_id,
                        "user_id": ex.user_id,
                        "file_name": ex.file_name,
                        "url": ex.url,
                        "few_shot_examples": ex.few_shot_examples,
                        "created_at": ex.created_at.isoformat() if ex.created_at else None
                    }
                    for ex in examples
                ]
                logger.info(f"Found {len(examples_dict)} few-shot example records for agent_id={agent_id}")
                return {"record": examples_dict, "message": "Few-shot examples found", "status": True}
            return {"record": None, "message": "No few-shot examples found", "status": False}
    except Exception as e:
        logger.error(f"Error in list_fewshot_examples_from_db: {str(e)}")
        return {"record": None, "message": f"Error: {str(e)}", "status": False}

async def update_fewshot_examples(user_id: str, agent_id: str, few_shot_examples: str, db_id: Optional[str] = None):
    """
    Update few-shot examples by agent_id.

    Args:
        user_id: User ID (optional, for backward compatibility)
        agent_id: Agent ID (primary identifier)
        few_shot_examples: Few-shot examples to update
        db_id: Database ID (defaults to the agent's primary DB)
    """
    try:
        db_id = db_id or await get_primary_db_id(agent_id)
        async for session in get_async_session():
            res = await session.execute(
                select(FewShotExamples).where(
                    FewShotExamples.agent_id == agent_id,
                    FewShotExamples.db_id == db_id
                )
            )
            record = res.first()
            if not record:
                return {"message": "No few-shot examples found", "status": False}
            record = record[0]  # Unpack ORM object from tuple
            record.few_shot_examples = few_shot_examples
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

    Args:
        user_id: User ID (optional, for backward compatibility)
        agent_id: Agent ID (primary identifier)
        nl_query: Natural language query (for backward compatibility)
        db_id: Database ID (defaults to the agent's primary DB)
    """
    try:
        db_id = db_id or await get_primary_db_id(agent_id)
        async for session in get_async_session():
            res = await session.execute(
                select(FewShotExamples).where(
                    FewShotExamples.agent_id == agent_id,
                    FewShotExamples.db_id == db_id
                )
            )
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

async def overwrite_fewshot_examples(user_id: str, agent_id: str, examples_list_or_json, file_name: str = "", db_id: Optional[str] = None, is_delete: bool = False):
    """
    Overwrite few-shot examples by agent_id.

    Args:
        user_id: User ID (optional, for backward compatibility)
        agent_id: Agent ID (primary identifier)
        examples_list_or_json: Examples to overwrite (list or JSON string)
        file_name: Optional file name
        db_id: Database ID (defaults to the agent's primary DB)
        is_delete: True when the overwrite is how a delete is performed — deleting
            examples rewrites the row with the survivors, so the row lives on and the
            delete audit (deleted_at/deleted_by) lands on it. False for a plain edit,
            which must not be recorded as a delete.
    """
    try:
        db_id = db_id or await get_primary_db_id(agent_id)
        async for session in get_async_session():
            res = await session.execute(
                select(FewShotExamples).where(
                    FewShotExamples.agent_id == agent_id,
                    FewShotExamples.db_id == db_id
                )
            )
            record = res.first()
            payload = examples_list_or_json
            if not isinstance(examples_list_or_json, str):
                try:
                    payload = __import__('json').dumps(examples_list_or_json)
                except Exception:
                    payload = "[]"
            if record:
                db_obj = record[0]
                if file_name:
                    db_obj.file_name = file_name
                db_obj.few_shot_examples = payload
                db_obj.updated_at = datetime.utcnow()
                if is_delete:
                    db_obj.deleted_at = db_obj.updated_at
                if user_id:
                    db_obj.updated_by = user_id  # acting dashboard user on this edit
                    if is_delete:
                        db_obj.deleted_by = user_id  # ...who performed the delete
                    if not db_obj.user_id:
                        db_obj.user_id = user_id  # adopt as creator if it was never recorded
            else:
                db_obj = FewShotExamples(
                    user_id=user_id,
                    chatbot_id=agent_id,  # Sync both IDs for consistency
                    agent_id=agent_id,
                    db_id=db_id,
                    file_name=file_name,
                    few_shot_examples=payload,
                    updated_at=datetime.utcnow()
                )
                session.add(db_obj)
            await session.commit()
            return {"message": "Few-shot examples overwritten successfully", "status": True}
    except Exception as e:
        logger.error(f"Exception in overwrite_fewshot_examples: {str(e)}")
        return {"message": f"Error in overwrite_fewshot_examples: {str(e)}", "status": False}
