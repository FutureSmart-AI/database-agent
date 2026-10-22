import json
from typing import List, Dict, Any, Optional
from fastapi import HTTPException, UploadFile
from logger import logger
from knowledge.db_utils import few_shot_db_utils
from knowledge.utils import common_utils
from chatbot_management.db_utils.chatbot_params_db_utils import get_chatbot_details_by_agent_id

from agent.utils.few_shot_utils import get_few_shot_service

async def get_all_agent_fewshot_examples(agent_id: str) -> List[Dict[str, str]]:
    """
    Get all few-shot examples for an agent
    """
    # Verify agent exists
    agent = await get_chatbot_details_by_agent_id(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    # Get few-shot examples
    db_res = await few_shot_db_utils.list_fewshot_examples_from_db(None, agent_id)
    
    if db_res and db_res.get("status") and db_res.get("record"):
        records = db_res.get("record")
        all_examples = []
        for rec in records:
            examples = rec.get("few_shot_examples", [])
            if isinstance(examples, str):
                try:
                    examples = json.loads(examples)
                except:
                    examples = []
            if isinstance(examples, list):
                all_examples.extend(examples)
        
        # Convert to response format
        response_data = []
        for example in all_examples:
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
    few_shot_examples_form: Optional[str] = None
) -> Dict[str, Any]:
    """
    Upload few-shot examples for an agent (bulk)
    """
    # Verify agent exists
    agent = await get_chatbot_details_by_agent_id(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    
    db_owner_id = agent.owner_id

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
    db_res = await few_shot_db_utils.upload_to_db_few_shot(None, agent_id, examples_json, file_name)

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
                    }, owner_id=db_owner_id)
            return {"message": "Few-shot examples uploaded successfully"}
        except Exception as ve:
            logger.error(f"Vector store upload failed: {ve}")
            return {"message": "Few-shot examples uploaded to database only, vector store failed"}

    raise HTTPException(status_code=500, detail="Few-shot examples failed to upload")

async def update_agent_fewshot_examples(
    agent_id: str,
    content_type: str,
    raw_body: bytes = None,
    file: Optional[UploadFile] = None,
    few_shot_examples_form: Optional[str] = None
) -> Dict[str, Any]:
    """
    Update (merge) few-shot examples for an agent
    """
    # Verify agent exists
    agent = await get_chatbot_details_by_agent_id(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    
    db_owner_id = agent.owner_id
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
                examples, file_name = await common_utils.extract_from_csv(file, mode="nl2sql_examples")
                for example in examples:
                    natural_query = example.get('\ufeffnatural_query') or example.get('natural_query')
                    sql_query = example.get('sql_query')
                    if natural_query and sql_query:
                        update_list.append({natural_query: sql_query})
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
    db_existing = await few_shot_db_utils.list_fewshot_examples_from_db(None, agent_id)
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

    # Upload merged
    db_res = await few_shot_db_utils.overwrite_fewshot_examples(None, agent_id, json.dumps(final_examples), file_name)

    if db_res and db_res.get("status"):
        try:
            vector_store = await get_few_shot_service()
            # In update, we clear and re-add for simplicity/consistency
            try:
                existing = await vector_store.get_examples(db_owner_id, agent_id)
                if existing:
                    for ex in existing:
                        await vector_store.delete_example(db_owner_id, agent_id, ex.get("question", ""))
            except Exception:
                pass

            for ex in final_examples:
                for query, sql in ex.items():
                    await vector_store.add_example(db_owner_id, agent_id, {
                        "id": query,
                        "question": query,
                        "sql_query": sql
                    }, owner_id=db_owner_id)
            return {"message": "Few-shot examples updated successfully"}
        except Exception as ve:
            logger.error(f"Vector store update failed: {ve}")
            return {"message": "Few-shot examples updated in database only, vector store failed"}

    raise HTTPException(status_code=500, detail="Failed to update few-shot examples")

async def delete_single_fewshot_example(agent_id: str, nl_query: str) -> Dict[str, Any]:
    """
    Delete a single few-shot example for an agent
    """
    # Verify agent exists
    agent = await get_chatbot_details_by_agent_id(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    # Get current examples
    db = await few_shot_db_utils.list_fewshot_examples_from_db(None, agent_id)
    if not db or not db.get("status") or not db.get("record"):
        return {"message": "No few-shot examples found", "status": False}

    record = db.get("record")
    if isinstance(record, list) and len(record) > 0:
        record = record[0]

    few_shot_examples = []
    raw = record.get("few_shot_examples")
    try:
        few_shot_examples = json.loads(raw) if isinstance(raw, str) else (raw or [])
    except:
        few_shot_examples = []

    def _norm(s: str) -> str:
        return " ".join((s or "").strip().split()).lower()
    target = _norm(nl_query)

    filtered_data = []
    to_delete = []
    for example in few_shot_examples:
        if isinstance(example, dict):
            kept = {}
            for key, val in example.items():
                if _norm(key) == target:
                    to_delete.append(key)
                else:
                    kept[key] = val
            if kept:
                filtered_data.append(kept)

    # Overwrite
    db_res = await few_shot_db_utils.overwrite_fewshot_examples(None, agent_id, filtered_data, record.get("file_name", ""))

    if db_res and db_res.get("status"):
        try:
            vector_store = await get_few_shot_service()
            db_owner_id = agent.owner_id
            for example_id in to_delete:
                await vector_store.delete_example(db_owner_id, agent_id, example_id)
            return {"message": "Few Shot Examples deleted successfully from both databases", "status": True}
        except Exception as ve:
            logger.error(f"Vector store deletion failed: {ve}")
            return {"message": "Few Shot Examples deleted from PostgreSQL only, vector store failed", "status": True}

    return {"message": "Few Shot Examples failed to be deleted", "status": False}

