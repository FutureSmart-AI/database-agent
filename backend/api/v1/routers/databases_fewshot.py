"""
RESTful API endpoints for per-Database Few-Shot Examples Management

Mirrors the global few-shot endpoints (api/v1/routers/fewshot.py) but scopes
every operation to a specific database (db_id) of an agent.
"""
from fastapi import HTTPException, Depends, APIRouter, Path, File, UploadFile, Form, Query
from starlette.requests import Request
from chatbot_management.utils.api_validation import get_api_key_or_session
from chatbot_management.services.logger import logger
import traceback
from typing import Optional

from agent.utils.authorization import require_agent_permission
from api.v1.schemas.fewshot import BulkDeleteFewShotRequest
from api.v1.utils.fewshot_helper import (
    get_all_agent_fewshot_examples, upload_agent_fewshot_examples,
    update_agent_fewshot_examples,
    delete_agent_fewshot_examples,
)

router = APIRouter(prefix="/v1")


@router.get("/agents/{agent_id}/databases/{db_id}/few-shot-examples")
async def get_all_few_shot_examples_for_db(
    agent_id: str = Path(..., description="Agent ID"),
    db_id: str = Path(..., description="Database ID"),
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("use")),
):
    """
    Get all few-shot examples for an agent scoped to a specific database

    """
    try:
        logger.info(f"Getting few-shot examples for agent {agent_id}, db {db_id}")
        return {"data": await get_all_agent_fewshot_examples(agent_id, db_id=db_id)}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting few-shot examples: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/agents/{agent_id}/databases/{db_id}/few-shot-examples")
async def create_few_shot_examples_for_db(
    agent_id: str = Path(..., description="Agent ID"),
    db_id: str = Path(..., description="Database ID"),
    request: Request = None,
    file: Optional[UploadFile] = File(None),
    few_shot_examples: Optional[str] = Form(None),
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("edit_agent")),
):
    """
    Upload/Create few-shot examples for an agent scoped to a specific database (bulk)

    """
    try:
        logger.info(f"Creating few-shot examples for agent {agent_id}, db {db_id}")

        content_type = request.headers.get('content-type', '')
        logger.info(f"POST /databases/{db_id}/few-shot-examples - Content-Type: {content_type}")

        raw_body = None
        if content_type.startswith("application/json"):
            raw_body = await request.body()

        return await upload_agent_fewshot_examples(
            agent_id, content_type, raw_body, file, few_shot_examples, db_id=db_id,
            user_id=auth.get("user_id"),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating few-shot examples: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.put("/agents/{agent_id}/databases/{db_id}/few-shot-examples")
async def update_few_shot_examples_for_db(
    agent_id: str = Path(..., description="Agent ID"),
    db_id: str = Path(..., description="Database ID"),
    request: Request = None,
    file: Optional[UploadFile] = File(None),
    few_shot_examples: Optional[str] = Form(None),
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("edit_agent")),
):
    """
    Update few-shot examples for an agent scoped to a specific database (bulk)

    """
    try:
        logger.info(f"Updating few-shot examples for agent {agent_id}, db {db_id}")

        content_type = request.headers.get('content-type', '')
        logger.info(f"PUT /databases/{db_id}/few-shot-examples - Content-Type: {content_type}")

        raw_body = None
        if content_type.startswith("application/json"):
            raw_body = await request.body()

        return await update_agent_fewshot_examples(
            agent_id, content_type, raw_body, file, few_shot_examples, db_id=db_id,
            user_id=auth.get("user_id"),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating few-shot examples: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.delete("/agents/{agent_id}/databases/{db_id}/few-shot-examples")
async def delete_few_shot_examples_for_db(
    body: BulkDeleteFewShotRequest,
    agent_id: str = Path(..., description="Agent ID"),
    db_id: str = Path(..., description="Database ID"),
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("edit_agent")),
):
    """
    Delete few-shot examples for an agent scoped to a specific database.

    - One or many: `{"nl_queries": ["...", "..."]}`
    - All: `{"delete_all": true}`
    """
    try:
        if body.delete_all or body.nl_queries:
            return await delete_agent_fewshot_examples(
                agent_id, db_id=db_id, user_id=auth.get("user_id"),
                nl_queries=body.nl_queries, delete_all=body.delete_all,
            )
        raise HTTPException(
            status_code=400,
            detail="Provide 'nl_queries' (one or more) or 'delete_all': true",
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Exception in delete_few_shot_examples_for_db: {str(e)}")
        return {"message": f"Error in delete_few_shot_examples_for_db : {str(e)}", "status": False}
