"""
Per-database (db_id-scoped) Tables & Columns endpoints (multi-db-spec.md §8.4, §8.6).
Mirror the agent-global tables.py / columns.py routes with `/databases/{db_id}` inserted,
forwarding db_id to the existing helpers (which scope metadata by db_id).
"""
import traceback
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path, File, UploadFile, Form, Query
from starlette.requests import Request

from chatbot_management.utils.api_validation import get_api_key_or_session
from chatbot_management.services.logger import logger
from agent.utils.authorization import require_agent_permission
from agent.utils.model_profiles import ProviderCredentialError

from api.v1.schemas.tables import SingleTableVisibilityRequest, SingleTableUpdateRequest, DeleteTablesRequest
from api.v1.schemas.columns import BulkColumnDescriptionsRequest, SingleColumnDescriptionRequest
from api.v1.utils.tables_helper import (
    get_all_agent_table_descriptions, create_agent_table_descriptions,
    update_agent_table_descriptions, update_specific_agent_table_description,
    delete_agent_table_descriptions, update_agent_table_visibility,
)
from api.v1.utils.columns_helper import (
    get_columns_with_descriptions, update_table_column_descriptions,
)

router = APIRouter(prefix="/v1")


@router.get("/agents/{agent_id}/databases/{db_id}/tables", tags=["Tables (per-DB)"])
async def db_list_tables(
    agent_id: str = Path(...),
    db_id: str = Path(...),
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("use")),
):
    try:
        return {"data": await get_all_agent_table_descriptions(agent_id, db_id=db_id)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing tables for db {db_id}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")


@router.post("/agents/{agent_id}/databases/{db_id}/tables", tags=["Tables (per-DB)"])
async def db_create_tables(
    agent_id: str = Path(...),
    db_id: str = Path(...),
    request: Request = None,
    file: Optional[UploadFile] = File(None),
    table_descriptions: Optional[str] = Form(None),
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("write")),
):
    try:
        content_type = request.headers.get("content-type", "")
        raw_body = await request.body() if content_type.startswith("application/json") else None
        return await create_agent_table_descriptions(
            agent_id, content_type, raw_body, file, table_descriptions, db_id=db_id,
            user_id=auth.get("user_id"),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating tables for db {db_id}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")


@router.put("/agents/{agent_id}/databases/{db_id}/tables", tags=["Tables (per-DB)"])
async def db_put_tables(
    agent_id: str = Path(...),
    db_id: str = Path(...),
    request: Request = None,
    file: Optional[UploadFile] = File(None),
    table_descriptions: Optional[str] = Form(None),
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("write")),
):
    """Bulk update table descriptions for a db_id — merges into the existing set (does not blank
    tables absent from the payload). Accepts a bare [{table_name, description}] array, a
    {"tables": [...]} object, or a file. Returns an "updated" message."""
    try:
        content_type = request.headers.get("content-type", "")
        raw_body = await request.body() if content_type.startswith("application/json") else None
        return await update_agent_table_descriptions(
            agent_id, content_type, raw_body, file, table_descriptions, db_id=db_id,
            user_id=auth.get("user_id"),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating tables for db {db_id}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")


@router.delete("/agents/{agent_id}/databases/{db_id}/tables", tags=["Tables (per-DB)"])
async def db_delete_tables(
    body: DeleteTablesRequest,
    agent_id: str = Path(...),
    db_id: str = Path(...),
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("write")),
):
    """Clear table descriptions. Body: {"table_names": ["t1","t2"]} for some, or {"delete_all": true} for all.
    (Tables are not deleted — only their description text is cleared.)"""
    try:
        if not body.delete_all and not body.table_names:
            raise HTTPException(status_code=400, detail="Provide 'table_names' (a non-empty list) or 'delete_all': true")
        deleted = await delete_agent_table_descriptions(
            agent_id, body.table_names, db_id=db_id, delete_all=body.delete_all,
            user_id=auth.get("user_id"),
        )
        if not deleted:
            return {"status": "success", "deleted": [], "message": "No table descriptions to delete."}
        noun = "description" if len(deleted) == 1 else "descriptions"
        return {"status": "success", "deleted": deleted, "message": f"Table {noun} deleted successfully."}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error bulk-deleting tables for db {db_id}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")


@router.post("/agents/{agent_id}/databases/{db_id}/tables/generate", status_code=202, tags=["Tables (per-DB)"])
async def db_generate_table_descriptions(
    agent_id: str = Path(...),
    db_id: str = Path(...),
    overwrite: bool = Query(False, description="true = regenerate ALL tables; false (default) = only fill tables whose description is blank (manual ones preserved)"),
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("write")),
):
    """Start an async job that auto-generates a description for every table in the DB (via LLM).
    `overwrite=true` regenerates all tables; default only fills tables whose description is
    currently blank (manually-set ones are preserved). Poll the returned job_id."""
    try:
        from api.v1.utils.description_jobs_helper import start_table_description_job
        return await start_table_description_job(agent_id, db_id, overwrite=overwrite)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting table description job for db {db_id}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")


@router.get("/agents/{agent_id}/databases/{db_id}/tables/generate/{job_id}", tags=["Tables (per-DB)"])
async def db_poll_table_descriptions(
    agent_id: str = Path(...),
    db_id: str = Path(...),
    job_id: str = Path(...),
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("use")),
):
    """Poll a table-description generation job → {status, message, error}."""
    try:
        from api.v1.utils.description_jobs_helper import get_table_description_job
        return await get_table_description_job(agent_id, db_id, job_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error polling table description job {job_id}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")


@router.post("/agents/{agent_id}/databases/{db_id}/tables/{table_name}/generate", tags=["Tables (per-DB)"])
async def db_generate_one_table_description(
    agent_id: str = Path(...),
    db_id: str = Path(...),
    table_name: str = Path(...),
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("write")),
):
    """Auto-generate (LLM) + save the description for a SINGLE table. Synchronous — returns
    `{table_name, description}` directly (no job/poll). Other tables and flags are untouched."""
    try:
        from api.v1.utils.description_jobs_helper import generate_single_table_description
        return await generate_single_table_description(agent_id, db_id, table_name)
    except HTTPException:
        raise
    except ProviderCredentialError as e:
        raise HTTPException(status_code=400, detail={"code": e.code, "message": str(e)})
    except Exception as e:
        logger.error(f"Error generating description for table {table_name} in db {db_id}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")


@router.patch("/agents/{agent_id}/databases/{db_id}/tables/{table_name}/visibility", tags=["Tables (per-DB)"])
async def db_table_visibility(
    agent_id: str = Path(...),
    db_id: str = Path(...),
    table_name: str = Path(...),
    body: SingleTableVisibilityRequest = None,
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("write")),
):
    try:
        return await update_agent_table_visibility(agent_id, table_name, body.is_included, db_id=db_id, user_id=auth.get("user_id"))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating visibility for db {db_id}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")


@router.put("/agents/{agent_id}/databases/{db_id}/tables/{table_name}", tags=["Tables (per-DB)"])
async def db_update_table_description(
    agent_id: str = Path(...),
    db_id: str = Path(...),
    table_name: str = Path(...),
    body: SingleTableUpdateRequest = None,
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("write")),
):
    """Update the description for a single table in the given db_id."""
    try:
        return await update_specific_agent_table_description(agent_id, table_name, body, db_id=db_id, user_id=auth.get("user_id"))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating description for table {table_name} in db {db_id}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")


@router.get("/agents/{agent_id}/databases/{db_id}/tables/{table_name}/columns", tags=["Column Descriptions (per-DB)"])
async def db_get_columns(
    agent_id: str = Path(...),
    db_id: str = Path(...),
    table_name: str = Path(...),
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("use")),
):
    try:
        user_id = auth.get("user_id")
        return {"data": await get_columns_with_descriptions(user_id, agent_id, table_name, db_id=db_id)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting columns for db {db_id}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")


@router.put("/agents/{agent_id}/databases/{db_id}/tables/{table_name}/columns", tags=["Column Descriptions (per-DB)"])
async def db_update_columns(
    agent_id: str = Path(...),
    db_id: str = Path(...),
    table_name: str = Path(...),
    body: BulkColumnDescriptionsRequest = None,
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("write")),
):
    try:
        user_id = auth.get("user_id")
        return await update_table_column_descriptions(user_id, agent_id, table_name, body, db_id=db_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating columns for db {db_id}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")
