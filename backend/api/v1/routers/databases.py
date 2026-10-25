"""
RESTful endpoints for the Multi-DB `databases` collection.
See docs/multi-db-spec.md §8.1–8.3 (CRUD, RDS discovery, bulk import) and §8.2 (auto-generate
description). One agent can own many source databases; each query is routed to one of them.
"""
import traceback
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path, UploadFile, File
from fastapi.responses import JSONResponse
from starlette.requests import Request

from chatbot_management.utils.api_validation import get_api_key_or_session
from chatbot_management.services.logger import logger
from agent.utils.authorization import require_agent_permission

from api.v1.schemas.databases import (
    AddDatabaseRequest, UpdateDatabaseRequest, DatabaseStatusRequest,
    DatabaseDescriptionRequest, RdsListRequest, TestConnectionRequest,
    BulkDeleteDatabasesRequest,
)
from api.v1.utils.databases_helper import (
    list_agent_databases, add_agent_database, get_agent_database, update_agent_database,
    delete_agent_database, set_database_status, set_database_description,
    list_rds_databases, bulk_import_databases, test_connection, check_all_databases,
    bulk_delete_databases,
)

router = APIRouter(prefix="/v1")


# ── Connection test & RDS discovery (not agent-scoped) ───────────────────────
@router.post("/databases/test")
async def test_database_connection(
    body: TestConnectionRequest,
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
):
    """Test a database connection without saving it (Add modal 'Test', RDS step 2, Retry)."""
    try:
        return await test_connection(body)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error testing connection: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")


@router.post("/databases/rds/list")
async def rds_list(
    body: RdsListRequest,
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
):
    """List databases (and table counts) available on an RDS instance."""
    try:
        return await list_rds_databases(body)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing RDS databases: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")


# ── Collection ───────────────────────────────────────────────────────────────
@router.get("/agents/{agent_id}/databases")
async def list_databases(
    agent_id: str = Path(...),
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("use")),
):
    try:
        return {"data": await list_agent_databases(agent_id)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing databases: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")


@router.post("/agents/{agent_id}/databases", status_code=201)
async def add_database(
    agent_id: str = Path(...),
    body: AddDatabaseRequest = None,
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("edit_agent")),
):
    try:
        result = await add_agent_database(agent_id, body)
        # Profile HC columns for the newly added DB in the background. The legacy single-DB route
        # and the multi-DB PATCH already do this; the multi-DB add path did not, so a new agent had
        # no HC profiles until someone called the HC-profile API by hand.
        db_id = result.get("db_id") if isinstance(result, dict) else None
        if db_id:
            try:
                from api.v1.routers.database import _run_hc_profiling_background, _hc_background_tasks
                import asyncio
                task = asyncio.create_task(_run_hc_profiling_background(agent_id, None, db_id=db_id))
                _hc_background_tasks.add(task)
                task.add_done_callback(_hc_background_tasks.discard)
            except Exception as e:
                logger.warning(f"[add_db] HC profile scheduling failed: {e}")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding database: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")


# ── Check all DB status (static path before /{db_id}) ────────────────────────
@router.post("/agents/{agent_id}/databases/check")
async def check_databases(
    agent_id: str = Path(...),
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("use")),
):
    """Health-check every DB (connection status + response time + description status)."""
    try:
        return await check_all_databases(agent_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error checking databases: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")


# ── Bulk import (static path before /{db_id}) ────────────────────────────────
@router.post("/agents/{agent_id}/databases/bulk")
async def bulk_import(
    agent_id: str = Path(...),
    file: UploadFile = File(...),
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("edit_agent")),
):
    try:
        raw = await file.read()
        result = await bulk_import_databases(agent_id, raw, file.filename or "")
        return JSONResponse(status_code=207, content=result)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in bulk import: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")


@router.post("/agents/{agent_id}/databases/bulk-delete")
async def bulk_delete(
    body: BulkDeleteDatabasesRequest,
    agent_id: str = Path(...),
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("edit_agent")),
):
    """Delete multiple databases (and their scoped metadata) in a single action.
    Body: {"db_ids": ["DB_...", "DB_..."]}. Best-effort per DB; returns per-DB results + a summary."""
    try:
        result = await bulk_delete_databases(agent_id, body.db_ids, user_id=auth.get("user_id"))
        return JSONResponse(status_code=207, content=result)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in bulk delete: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")


# ── Auto-generate description (static paths before /{db_id} item routes) ──────
@router.post("/agents/{agent_id}/databases/{db_id}/description/generate", status_code=202)
async def generate_description(
    agent_id: str = Path(...),
    db_id: str = Path(...),
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("edit_agent")),
):
    try:
        from api.v1.utils.description_jobs_helper import start_description_job
        # Explicit Generate: persist the result onto the DB on completion (overwrite an existing one).
        return await start_description_job(agent_id, db_id, apply_to_db=True, overwrite=True)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting description job: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")


@router.get("/agents/{agent_id}/databases/{db_id}/description/generate/{job_id}")
async def poll_description(
    agent_id: str = Path(...),
    db_id: str = Path(...),
    job_id: str = Path(...),
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("use")),
):
    try:
        from api.v1.utils.description_jobs_helper import get_description_job
        return await get_description_job(agent_id, db_id, job_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error polling description job: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")


# ── Item ─────────────────────────────────────────────────────────────────────
@router.get("/agents/{agent_id}/databases/{db_id}")
async def get_database(
    agent_id: str = Path(...),
    db_id: str = Path(...),
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("edit_agent")),
):
    try:
        return await get_agent_database(agent_id, db_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting database: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")


@router.patch("/agents/{agent_id}/databases/{db_id}")
async def update_database(
    agent_id: str = Path(...),
    db_id: str = Path(...),
    body: UpdateDatabaseRequest = None,
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("edit_agent")),
):
    try:
        result = await update_agent_database(agent_id, db_id, body, user_id=auth.get("user_id"))
        if result.get("db_changed"):
            # Re-profile HC for this DB in the background (mirrors legacy PUT-connection behaviour).
            try:
                from api.v1.routers.database import _run_hc_profiling_background, _hc_background_tasks
                import asyncio
                task = asyncio.create_task(_run_hc_profiling_background(agent_id, None, db_id=db_id))
                _hc_background_tasks.add(task)
                task.add_done_callback(_hc_background_tasks.discard)
            except Exception as e:
                logger.warning(f"[update_db] HC re-profile scheduling failed: {e}")
        return {"message": result.get("message"), "db_id": db_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating database: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")


@router.delete("/agents/{agent_id}/databases/{db_id}", status_code=204)
async def delete_database(
    agent_id: str = Path(...),
    db_id: str = Path(...),
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("edit_agent")),
):
    try:
        await delete_agent_database(agent_id, db_id, user_id=auth.get("user_id"))
        return None
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting database: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")


@router.patch("/agents/{agent_id}/databases/{db_id}/status")
async def update_database_status(
    agent_id: str = Path(...),
    db_id: str = Path(...),
    body: DatabaseStatusRequest = None,
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("edit_agent")),
):
    try:
        return await set_database_status(agent_id, db_id, body.is_active, user_id=auth.get("user_id"))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating database status: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")


@router.patch("/agents/{agent_id}/databases/{db_id}/description")
async def update_database_description(
    agent_id: str = Path(...),
    db_id: str = Path(...),
    body: DatabaseDescriptionRequest = None,
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("edit_agent")),
):
    try:
        return await set_database_description(agent_id, db_id, body.description, user_id=auth.get("user_id"))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating database description: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")
