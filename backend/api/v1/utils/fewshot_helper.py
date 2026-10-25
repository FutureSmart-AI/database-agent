import json
from typing import List, Dict, Any, Optional
from fastapi import HTTPException, UploadFile
from chatbot_management.services.logger import logger
from agent.db_utils import few_shot_db_utils
from knowledge.db_utils import few_shot_db_utils as knowledge_few_shot_db_utils
from agent.utils import common_utils
from chatbot_management.services.sqlmodel_session import get_async_session
from models.sql_models import ChatbotDetails
from sqlmodel import select

from agent.utils.few_shot_utils import get_few_shot_service
from agent.db_utils.database_db_utils import get_primary_db_id


async def verify_agent_exists(agent_id: str):
    """Verify that an agent exists in the database"""
    async for session in get_async_session():
        result = await session.execute(select(ChatbotDetails).where(ChatbotDetails.agent_id == agent_id))
        agent = result.scalar_one_or_none()
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
        return agent


async def get_all_agent_fewshot_examples(agent_id: str, db_id: Optional[str] = None) -> List[Dict[str, str]]:
    """
    Get all few-shot examples for an agent
    """
    # Verify agent exists
    agent = await verify_agent_exists(agent_id)
    db_id = db_id or await get_primary_db_id(agent_id)

    # Get few-shot examples
    db_res = await few_shot_db_utils.list_fewshot_examples_from_db(None, agent_id, db_id=db_id)
    
    if db_res and db_res.get("status") and db_res.get("record"):
        record = db_res.get("record")
        examples = record.get("few_shot_examples", [])
        if isinstance(examples, str):
            try:
                examples = json.loads(examples)
            except:
                examples = []
        if not isinstance(examples, list):
            examples = []

        response_data = []
        for example in examples:
            if isinstance(example, dict):
                for natural_query, sql_query in example.items():
                    response_data.append({
                        "natural_query": natural_query,
                        "sql_query": sql_query
                    })
        return response_data

    return []

async def upload_agent_fewshot_examples(
    agent_id: str,
    content_type: str,
    raw_body: bytes = None,
    file: Optional[UploadFile] = None,
    few_shot_examples_form: Optional[str] = None,
    db_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Upload few-shot examples for an agent (bulk)
    """
    # Verify agent exists
    agent = await verify_agent_exists(agent_id)
    db_owner_id = agent.owner_id
    db_id = db_id or await get_primary_db_id(agent_id)

    file_name = ""
    few_shot_examples = []

    try:
        # Priority 1: JSON body
        if content_type.startswith("application/json"):
            if raw_body:
                data = json.loads(raw_body.decode())
                if isinstance(data, dict) and "examples" in data:
                    few_shot_examples = [
                        {example["natural_query"]: example["sql_query"]}
                        for example in data["examples"]
                    ]
                elif isinstance(data, list):
                    few_shot_examples = data
                else:
                    raise HTTPException(status_code=400, detail="Invalid JSON format for few-shot examples")
        # Priority 2: File upload
        elif file and file.filename:
            if few_shot_examples_form and few_shot_examples_form not in [None, "", "string"]:
                raise HTTPException(status_code=400, detail="Provide either 'file' or 'few_shot_examples', not both")

            if file.filename.endswith('.json'):
                contents = await file.read()
                data = json.loads(contents.decode('utf-8'))
                if isinstance(data, dict) and "examples" in data:
                    few_shot_examples = [
                        {example["natural_query"]: example["sql_query"]}
                        for example in data["examples"]
                    ]
                elif isinstance(data, list):
                    few_shot_examples = data
                else:
                    raise HTTPException(status_code=400, detail="Invalid JSON file format")
                file_name = file.filename
            else:
                # Mode should be "nl2sql_examples" as in router
                few_shot_examples, file_name = await common_utils.extract_from_csv(file, mode="nl2sql_examples")
        # Priority 3: Form field JSON string
        elif few_shot_examples_form and few_shot_examples_form not in [None, "", "string"]:
            data = json.loads(few_shot_examples_form)
            if isinstance(data, dict) and "examples" in data:
                few_shot_examples = [
                    {example["natural_query"]: example["sql_query"]}
                    for example in data["examples"]
                ]
            elif isinstance(data, list):
                few_shot_examples = data
            else:
                few_shot_examples = data
        else:
            raise HTTPException(status_code=400, detail="Provide few-shot examples via JSON body, file upload, or few_shot_examples field")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error loading data: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Error loading data: {str(e)}")

    if not few_shot_examples:
        raise HTTPException(status_code=400, detail="No few-shot examples provided")

    examples_json = json.dumps(few_shot_examples)
    noun = "example" if len(few_shot_examples) == 1 else "examples"
    db_res = await few_shot_db_utils.upload_to_db_few_shot(user_id, agent_id, examples_json, file_name, db_id=db_id)

    if db_res and db_res.get("status"):
        # Update Vector Store
        try:
            vector_store = await get_few_shot_service()
            for example in few_shot_examples:
                for query, sql in example.items():
                    await vector_store.add_example(db_owner_id, agent_id, {
                        "id": query,
                        "question": query,
                        "sql_query": sql
                    }, owner_id=db_owner_id, db_id=db_id)
            return {"message": f"Few-shot {noun} uploaded successfully."}
        except Exception as ve:
            logger.error(f"Vector store upload failed: {ve}", exc_info=True)
            return {"message": f"Few-shot {noun} uploaded to database only, vector store failed",
                    "vector_store_error": str(ve),
                    "vector_store_error_type": type(ve).__name__}

    raise HTTPException(status_code=500, detail="Few-shot examples failed to upload")

async def update_agent_fewshot_examples(
    agent_id: str,
    content_type: str,
    raw_body: bytes = None,
    file: Optional[UploadFile] = None,
    few_shot_examples_form: Optional[str] = None,
    db_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Update (merge) few-shot examples for an agent
    """
    # Verify agent exists
    agent = await verify_agent_exists(agent_id)
    db_owner_id = agent.owner_id
    db_id = db_id or await get_primary_db_id(agent_id)
    update_list = []
    file_name = ""

    try:
        # Priority 1: JSON body
        if content_type.startswith("application/json"):
            if raw_body:
                data = json.loads(raw_body.decode())
                if isinstance(data, dict) and "examples" in data:
                    update_list = [
                        {example["natural_query"]: example["sql_query"]}
                        for example in data["examples"]
                    ]
                elif isinstance(data, list):
                    update_list = data
                else:
                    raise HTTPException(status_code=400, detail="Invalid JSON format")
        # Priority 2: File upload
        elif file and file.filename:
            if few_shot_examples_form and few_shot_examples_form not in [None, "", "string"]:
                raise HTTPException(status_code=400, detail="Provide either 'file' or 'few_shot_examples', not both")

            if file.filename.endswith('.json'):
                contents = await file.read()
                data = json.loads(contents.decode('utf-8'))
                if isinstance(data, dict) and "examples" in data:
                    update_list = [
                        {example["natural_query"]: example["sql_query"]}
                        for example in data["examples"]
                    ]
                elif isinstance(data, list):
                    update_list = data
                else:
                    raise HTTPException(status_code=400, detail="Invalid JSON file format")
                file_name = file.filename
            else:
                # extract_from_csv already returns the {query: sql} shape (accepts question,sql
                # or natural_query,sql_query) \u2014 use it directly, same as upload.
                update_list, file_name = await common_utils.extract_from_csv(file, mode="nl2sql_examples")
        # Priority 3: Form field JSON string
        elif few_shot_examples_form and few_shot_examples_form not in [None, "", "string"]:
            data = json.loads(few_shot_examples_form)
            if isinstance(data, dict) and "examples" in data:
                update_list = [
                    {example["natural_query"]: example["sql_query"]}
                    for example in data["examples"]
                ]
            elif isinstance(data, list):
                update_list = data
            else:
                update_list = data
        else:
            raise HTTPException(status_code=400, detail="Provide examples via JSON body, file upload, or few_shot_examples field")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error loading data: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Error loading data: {str(e)}")

    if not update_list:
        raise HTTPException(status_code=400, detail="No examples provided")

    # Fetch existing examples from DB
    db_existing = await few_shot_db_utils.list_fewshot_examples_from_db(None, agent_id, db_id=db_id)
    existing_examples = []
    if db_existing and db_existing.get("status") and db_existing.get("record"):
        record = db_existing.get("record")
        if isinstance(record, list) and len(record) > 0:
            record = record[0]
        raw_existing = record.get("few_shot_examples")
        try:
            existing_examples = json.loads(raw_existing) if isinstance(raw_existing, str) else (raw_existing or [])
        except:
            existing_examples = []

    # Merge logic
    def _norm(s: str) -> str:
        return " ".join((s or "").strip().split()).lower()

    examples_dict = {}
    norm_to_actual = {}
    
    for example in existing_examples:
        if isinstance(example, dict):
            for k, v in example.items():
                kn = _norm(k)
                examples_dict[kn] = v
                norm_to_actual[kn] = k

    for example in update_list:
        if isinstance(example, dict):
            for k, v in example.items():
                kn = _norm(k)
                examples_dict[kn] = v
                norm_to_actual[kn] = k

    final_examples = [{norm_to_actual[kn]: v} for kn, v in examples_dict.items()]
    noun = "example" if len(update_list) == 1 else "examples"

    # Upload merged
    db_res = await knowledge_few_shot_db_utils.overwrite_fewshot_examples(user_id, agent_id, json.dumps(final_examples), file_name, db_id=db_id)

    if db_res and db_res.get("status"):
        try:
            vector_store = await get_few_shot_service()
            # In update, we clear and re-add for simplicity/consistency
            try:
                existing = await vector_store.get_examples(db_owner_id, agent_id, db_id=db_id)
                if existing:
                    for ex in existing:
                        await vector_store.delete_example(db_owner_id, agent_id, ex.get("question", ""), db_id=db_id)
            except Exception:
                pass

            for ex in final_examples:
                for query, sql in ex.items():
                    await vector_store.add_example(db_owner_id, agent_id, {
                        "id": query,
                        "question": query,
                        "sql_query": sql
                    }, owner_id=db_owner_id, db_id=db_id)
            return {"message": f"Few-shot {noun} updated successfully."}
        except Exception as ve:
            logger.error(f"Vector store update failed: {ve}", exc_info=True)
            return {"message": f"Few-shot {noun} updated in database only, vector store failed",
                    "vector_store_error": str(ve),
                    "vector_store_error_type": type(ve).__name__}

    raise HTTPException(status_code=500, detail="Failed to update few-shot examples")

async def delete_agent_fewshot_examples(
    agent_id: str,
    db_id: Optional[str] = None,
    user_id: Optional[str] = None,
    nl_queries: Optional[List[str]] = None,
    delete_all: bool = False,
) -> Dict[str, Any]:
    """Delete multiple few-shot examples in one action — either the ones whose natural-language
    query matches `nl_queries`, or ALL of them when `delete_all=True`. Removes from both the DB
    and the vector store. Returns a count-aware message."""
    agent = await verify_agent_exists(agent_id)
    db_id = db_id or await get_primary_db_id(agent_id)

    db = await few_shot_db_utils.list_fewshot_examples_from_db(None, agent_id, db_id=db_id)
    if not db or not db.get("status") or not db.get("record"):
        return {"message": "No few-shot examples found.", "status": False, "deleted": 0}

    record = db.get("record")
    if isinstance(record, list) and len(record) > 0:
        record = record[0]
    raw = record.get("few_shot_examples")
    try:
        examples = json.loads(raw) if isinstance(raw, str) else (raw or [])
    except Exception:
        examples = []

    def _norm(s: str) -> str:
        return " ".join((s or "").strip().split()).lower()

    targets = set() if delete_all else {_norm(q) for q in (nl_queries or [])}

    filtered_data, to_delete = [], []
    for example in examples:
        if not isinstance(example, dict):
            continue
        kept = {}
        for key, val in example.items():
            if delete_all or _norm(key) in targets:
                to_delete.append(key)
            else:
                kept[key] = val
        if kept:
            filtered_data.append(kept)

    deleted = len(to_delete)
    if deleted == 0:
        return {"message": "No matching few-shot examples to delete.", "status": True, "deleted": 0}

    db_res = await knowledge_few_shot_db_utils.overwrite_fewshot_examples(
        user_id, agent_id, json.dumps(filtered_data), record.get("file_name", ""), db_id=db_id,
        is_delete=True,
    )
    noun = "example" if deleted == 1 else "examples"
    if db_res and db_res.get("status"):
        try:
            vector_store = await get_few_shot_service()
            db_owner_id = agent.owner_id
            for example_id in to_delete:
                await vector_store.delete_example(db_owner_id, agent_id, example_id, db_id=db_id)
            return {"message": f"Few-shot {noun} deleted successfully.", "status": True, "deleted": deleted}
        except Exception as ve:
            logger.error(f"Vector store bulk deletion failed: {ve}")
            return {"message": f"Few-shot {noun} deleted (database only; vector store update failed).",
                    "status": True, "deleted": deleted}

    return {"message": "Few-shot examples failed to be deleted.", "status": False, "deleted": 0}

