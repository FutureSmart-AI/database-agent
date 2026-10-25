"""
RESTful API endpoints for PER-DATABASE (db_id-scoped) High-Cardinality management.

Multi-DB feature (docs/multi-db-spec.md §8.7, §4). These routes mirror the
agent-global manual-HC routes (api/v1/routers/tables.py) and HC-profile routes
(api/v1/routers/hc_profile.py), but carry an explicit ``/databases/{db_id}``
path segment so every HC read/write/delete is scoped to one database.

Routes:
  GET    /v1/agents/{agent_id}/databases/{db_id}/tables/high-cardinality-columns
  POST   /v1/agents/{agent_id}/databases/{db_id}/tables/high-cardinality-columns
  DELETE /v1/agents/{agent_id}/databases/{db_id}/tables/high-cardinality-columns
  POST   /v1/agents/{agent_id}/databases/{db_id}/tables/hc-profile
  GET    /v1/agents/{agent_id}/databases/{db_id}/tables/hc-profile
  DELETE /v1/agents/{agent_id}/databases/{db_id}/tables/hc-profile
  GET    /v1/agents/{agent_id}/databases/{db_id}/tables/{table_name}/hc-profile
  DELETE /v1/agents/{agent_id}/databases/{db_id}/tables/{table_name}/hc-profile

This module does NOT register itself with the application; registration is done
by the caller.
"""
import asyncio
import json
import traceback
from typing import Any, Dict, List, Tuple

from fastapi import APIRouter, Body, Depends, HTTPException, Path
from starlette.requests import Request

from agent.utils.authorization import require_agent_permission
from agent.utils.heavy_work_gate import heavy_work
from agent.utils.high_cardinality_qdrant_utils import get_cardinality_store
from chatbot_management.services.logger import logger
from chatbot_management.utils.api_validation import get_api_key_or_session
from knowledge.db_utils import database_db_utils, table_description_db_utils
from knowledge.db_utils.hc_profile_db_utils import (
    delete_hc_column_profiles,
    get_all_hc_column_profiles,
    get_hc_column_profiles,
)
from api.v1.schemas.hc_profile import TriggerHCProfileRequest
from api.v1.schemas.tables import HighCardinalityColumnsRequest
from api.v1.routers.hc_profile import (
    _cleanup_qdrant_for_profiles,
    _get_agent,
    run_hc_profile_for_agent,
)
from api.v1.utils.tables_helper import get_agent_high_cardinality_columns

router = APIRouter(prefix="/v1")


# ===========================================================================
# Manual High-Cardinality Columns (per-DB)
# ===========================================================================

@router.get(
    "/agents/{agent_id}/databases/{db_id}/tables/high-cardinality-columns",
    tags=["High Cardinality Columns (per-DB)"],
)
async def get_high_cardinality_columns_for_db(
    agent_id: str = Path(..., description="Agent ID"),
    db_id: str = Path(..., description="Database ID"),
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("use")),
):
    """Get high-cardinality columns for an agent, scoped to a specific database."""
    try:
        user_id = auth.get("user_id")
        logger.info(
            f"Getting high cardinality columns for agent {agent_id} | db_id={db_id} | user_id={user_id}"
        )
        return {"data": await get_agent_high_cardinality_columns(agent_id, user_id, db_id=db_id)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting high cardinality columns: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")


@router.post(
    "/agents/{agent_id}/databases/{db_id}/tables/high-cardinality-columns",
    tags=["High Cardinality Columns (per-DB)"],
)
async def set_high_cardinality_columns_for_db(
    agent_id: str = Path(..., description="Agent ID"),
    db_id: str = Path(..., description="Database ID"),
    body: HighCardinalityColumnsRequest = Body(..., description="High cardinality columns configuration"),
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("edit_agent")),
):
    """Set high-cardinality columns for an agent, scoped to a specific database.

    Indexes the column values into the HC Qdrant collection (tagged with db_id),
    then merges the configuration into TableDescription. Mirrors the agent-global
    route but resolves the DB connection by db_id so the right database is read.
    """
    try:
        resolved_user_id = auth.get("user_id")
        logger.info(
            f"Setting high cardinality columns for agent {agent_id} | db_id={db_id} | user_id={resolved_user_id}"
        )

        columns_data: List[Dict[str, str]] = []
        if body and body.columns:
            columns_data = [
                {"table_name": col.table_name, "column_name": col.column_name}
                for col in body.columns
            ]
        if not columns_data:
            raise HTTPException(status_code=400, detail="No valid high cardinality columns provided")

        # Existing config (agent-global metadata)
        db = await table_description_db_utils.get_high_cardinality_columns(resolved_user_id, agent_id)
        record = db.get("record", None)
        existing_hc: Dict[str, Any] = {}
        if record is not None:
            val = getattr(record, "high_cardinality_columns", record)
            if isinstance(record, (tuple, list)) and len(record) > 0:
                val = record[0]
            if isinstance(val, str) and val:
                existing_hc = json.loads(val)
            elif val is not None:
                existing_hc = val

        table_columns_map: Dict[str, List[str]] = {}
        for col in columns_data:
            table_columns_map.setdefault(col["table_name"], []).append(col["column_name"])

        # Resolve the specific database connection
        db_conn_resp = await database_db_utils.get_db_connection_by_id(agent_id, db_id)
        if not (db_conn_resp and db_conn_resp.get("status") and db_conn_resp.get("db_details")):
            raise HTTPException(
                status_code=400,
                detail=f"No database connection found for db_id={db_id}; cannot validate columns",
            )
        db_details = db_conn_resp.get("db_details")

        # Validate requested columns exist, build new-pair set, then merge
        missing_columns_map: Dict[str, List[str]] = {}
        new_pairs: List[Tuple[str, str]] = []
        for table_name, column_names in table_columns_map.items():
            try:
                existing_cols = await database_db_utils.get_table_columns(db_details, table_name)
            except Exception as err:
                logger.warning(f"Failed to inspect table '{table_name}' for agent {agent_id}: {err}")
                missing_columns_map[table_name] = column_names
                continue

            not_found = [c for c in column_names if c not in existing_cols]
            if not_found:
                missing_columns_map[table_name] = not_found
                continue

            existing_for_tbl = existing_hc.get(table_name, []) or []
            if not isinstance(existing_for_tbl, list):
                existing_for_tbl = []
            for c in column_names:
                if c not in existing_for_tbl:
                    new_pairs.append((table_name, c))
            existing_hc[table_name] = list(set(existing_for_tbl + column_names))

        if missing_columns_map:
            raise HTTPException(status_code=400, detail={"missing_columns": missing_columns_map})

        new_pair_set = set(new_pairs)

        # Step 1: index values into Qdrant (tagged with db_id)
        qdrant_loaded: List[Tuple[str, str]] = []
        # Embedding the values is paid for by the agent owner's key policy.
        from agent.utils.provider_key_scope import owner_key_scope
        from chatbot_management.db_utils.bot_crud_db_utils import get_owner_email_by_agent_id
        # Reading and embedding whole columns is heavy setup work: one section at a time per
        # process, queued behind any running profiling job (DA-MEM-002).
        async with owner_key_scope(await get_owner_email_by_agent_id(agent_id)), \
                heavy_work(f"hc-register agent={agent_id} db={db_id}"):
            store = await get_cardinality_store()
            try:
                for table_name, column_names in table_columns_map.items():
                    for column_name in column_names:
                        unique_values = await asyncio.to_thread(
                            table_description_db_utils.get_unique_values_for_columns,
                            {"db_details": db_details}, table_name, [column_name],
                        )
                        values = [str(v) for v in unique_values.get(column_name, []) if v is not None]
                        if values:
                            await store.store_values(
                                values=values,
                                metadata={"table": table_name, "column": column_name, "db_id": db_id},
                            )
                            qdrant_loaded.append((table_name, column_name))
                            logger.info(
                                f"Loaded {len(values)} values into Qdrant for {table_name}.{column_name} (db_id={db_id})"
                            )
            except Exception as qdrant_err:
                logger.error(f"[HC] Vector DB indexing failed — aborting: {qdrant_err}")
                for tbl, col in qdrant_loaded:
                    if (tbl, col) in new_pair_set:
                        try:
                            await store.delete_values_for_table_column(tbl, col, db_id=db_id)
                        except Exception as rb_err:
                            logger.warning(f"[HC] Rollback delete failed for {tbl}.{col}: {rb_err}")
                raise HTTPException(
                    status_code=502,
                    detail={
                        "error": "vector_db_failure",
                        "message": "Failed to index column values in the vector database (Qdrant).",
                        "vector_db_error": str(qdrant_err),
                    },
                )

        # Step 2: persist merged config in metadata DB
        try:
            result = await table_description_db_utils.upload_high_cardinality_columns(
                resolved_user_id, agent_id, existing_hc
            )
            if isinstance(result, dict) and result.get("status") is False:
                raise RuntimeError(result.get("error") or "metadata write returned status=False")
        except HTTPException:
            raise
        except Exception as pg_err:
            logger.error(f"[HC] Metadata DB write failed; rolling back Qdrant for new pairs: {pg_err}")
            for tbl, col in qdrant_loaded:
                if (tbl, col) in new_pair_set:
                    try:
                        await store.delete_values_for_table_column(tbl, col, db_id=db_id)
                    except Exception as rb_err:
                        logger.warning(f"[HC] Rollback delete failed for {tbl}.{col}: {rb_err}")
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "metadata_db_failure",
                    "message": "Vector DB indexing succeeded but metadata DB write failed; rolled back.",
                    "metadata_db_error": str(pg_err),
                },
            )

        return {
            "status": "success",
            "columns_configured": len(columns_data),
            "new_columns_added": [{"table_name": t, "column_name": c} for t, c in new_pairs],
            "message": "High cardinality columns configured (metadata DB and vector DB are in sync)",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error setting high cardinality columns: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")


@router.delete(
    "/agents/{agent_id}/databases/{db_id}/tables/high-cardinality-columns",
    tags=["High Cardinality Columns (per-DB)"],
)
async def delete_high_cardinality_columns_for_db(
    agent_id: str = Path(..., description="Agent ID"),
    db_id: str = Path(..., description="Database ID"),
    body: HighCardinalityColumnsRequest = Body(..., description="High cardinality columns to remove"),
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("edit_agent")),
):
    """Delete specific high-cardinality columns for an agent, scoped to a database.

    Removes the columns from the config and best-effort deletes the matching
    db_id-scoped vectors from the HC Qdrant collection.
    """
    try:
        resolved_user_id = auth.get("user_id")
        logger.info(
            f"Deleting high cardinality columns for agent {agent_id} | db_id={db_id} | user_id={resolved_user_id}"
        )

        columns_to_remove: List[Dict[str, str]] = []
        if body and body.columns:
            columns_to_remove = [
                {"table_name": col.table_name, "column_name": col.column_name}
                for col in body.columns
            ]
        if not columns_to_remove:
            raise HTTPException(status_code=400, detail="No columns specified for removal")

        db = await table_description_db_utils.get_high_cardinality_columns(resolved_user_id, agent_id)
        record = db.get("record", None)
        existing_hc: Dict[str, Any] = {}
        if record is not None:
            val = getattr(record, "high_cardinality_columns", record)
            if isinstance(record, (tuple, list)) and len(record) > 0:
                val = record[0]
            if isinstance(val, str) and val:
                existing_hc = json.loads(val)
            elif val is not None:
                existing_hc = val

        if not existing_hc:
            raise HTTPException(status_code=404, detail="No high cardinality columns configured for this agent")

        removed_count = 0
        removed_pairs: List[Tuple[str, str]] = []
        for col in columns_to_remove:
            t, c = col["table_name"], col["column_name"]
            if t in existing_hc and isinstance(existing_hc[t], list) and c in existing_hc[t]:
                existing_hc[t].remove(c)
                removed_count += 1
                removed_pairs.append((t, c))
                if not existing_hc[t]:
                    del existing_hc[t]

        if removed_count == 0:
            raise HTTPException(
                status_code=404, detail="None of the specified columns were found in the configuration"
            )

        result = await table_description_db_utils.upload_high_cardinality_columns(
            resolved_user_id, agent_id, existing_hc
        )
        if result and result.get("status"):
            try:
                store = await get_cardinality_store()
                for t_name, c_name in removed_pairs:
                    try:
                        await store.delete_values_for_table_column(t_name, c_name, db_id=db_id)
                    except Exception as q_err:
                        logger.warning(
                            "Qdrant HC cleanup failed for %s.%s (db_id=%s, non-blocking): %s",
                            t_name, c_name, db_id, q_err,
                        )
            except Exception as store_err:
                logger.warning("Qdrant HC cleanup skipped (non-blocking): %s", store_err)

            return {"status": "success", "columns_removed": removed_count, "message": "High cardinality columns removed"}

        raise HTTPException(status_code=500, detail="Failed to remove high cardinality columns")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting high cardinality columns: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")


# ===========================================================================
# HC Profile (per-DB)
# ===========================================================================

@router.post(
    "/agents/{agent_id}/databases/{db_id}/tables/hc-profile",
    tags=["HC Column Profiling (per-DB)"],
)
async def trigger_hc_profile_for_db(
    agent_id: str = Path(..., description="Agent ID"),
    db_id: str = Path(..., description="Database ID"),
    body: TriggerHCProfileRequest = Body(default=TriggerHCProfileRequest()),
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("edit_agent")),
):
    """Trigger automatic profiling of a specific database's tables."""
    try:
        user_id = auth.get("user_id")
        logger.info(f"Triggering HC profile for agent {agent_id} | db_id={db_id} | user_id={user_id}")
        return await run_hc_profile_for_agent(user_id, agent_id, body, db_id=db_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error triggering HC profile: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")


@router.get(
    "/agents/{agent_id}/databases/{db_id}/tables/hc-profile",
    tags=["HC Column Profiling (per-DB)"],
)
async def get_all_hc_profiles_for_db(
    agent_id: str = Path(..., description="Agent ID"),
    db_id: str = Path(..., description="Database ID"),
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("use")),
):
    """Get stored HC column profiles for all profiled tables of a specific database."""
    try:
        logger.info(f"Getting all HC profiles for agent {agent_id} | db_id={db_id}")
        agent = await _get_agent(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
        result = await get_all_hc_column_profiles(agent_id, db_id=db_id)
        return {"data": result.get("records", [])}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting HC profiles: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")


@router.delete(
    "/agents/{agent_id}/databases/{db_id}/tables/hc-profile",
    tags=["HC Column Profiling (per-DB)"],
)
async def delete_all_hc_profiles_for_db(
    agent_id: str = Path(..., description="Agent ID"),
    db_id: str = Path(..., description="Database ID"),
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("edit_agent")),
):
    """Delete all stored HC column profiles for a specific database (and its Qdrant vectors)."""
    try:
        logger.info(f"Deleting all HC profiles for agent {agent_id} | db_id={db_id}")
        agent = await _get_agent(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
        existing = await get_all_hc_column_profiles(agent_id, db_id=db_id)
        records = existing.get("records", [])
        if records:
            await _cleanup_qdrant_for_profiles(records, db_id=db_id)
        result = await delete_hc_column_profiles(agent_id, db_id=db_id)
        if not result.get("status"):
            raise HTTPException(status_code=404, detail=result.get("message", "No profiles found"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting HC profiles: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")


@router.get(
    "/agents/{agent_id}/databases/{db_id}/tables/{table_name}/hc-profile",
    tags=["HC Column Profiling (per-DB)"],
)
async def get_table_hc_profile_for_db(
    agent_id: str = Path(..., description="Agent ID"),
    db_id: str = Path(..., description="Database ID"),
    table_name: str = Path(..., description="Table name"),
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("use")),
):
    """Get the stored HC column profile for a specific table in a specific database."""
    try:
        logger.info(f"Getting HC profile for table {table_name} in agent {agent_id} | db_id={db_id}")
        agent = await _get_agent(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
        result = await get_hc_column_profiles(agent_id, table_name, db_id=db_id)
        if not result.get("status"):
            raise HTTPException(status_code=404, detail=f"No HC profile found for table '{table_name}'")
        return {"data": result["record"]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting HC profile for table: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")


@router.delete(
    "/agents/{agent_id}/databases/{db_id}/tables/{table_name}/hc-profile",
    tags=["HC Column Profiling (per-DB)"],
)
async def delete_table_hc_profile_for_db(
    agent_id: str = Path(..., description="Agent ID"),
    db_id: str = Path(..., description="Database ID"),
    table_name: str = Path(..., description="Table name"),
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("edit_agent")),
):
    """Delete the stored HC column profile for a specific table in a specific database."""
    try:
        logger.info(f"Deleting HC profile for table {table_name} in agent {agent_id} | db_id={db_id}")
        agent = await _get_agent(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
        existing = await get_hc_column_profiles(agent_id, table_name, db_id=db_id)
        if existing.get("status") and existing.get("record"):
            await _cleanup_qdrant_for_profiles([existing["record"]], db_id=db_id)
        result = await delete_hc_column_profiles(agent_id, table_name, db_id=db_id)
        if not result.get("status"):
            raise HTTPException(
                status_code=404,
                detail=result.get("message", f"No profile found for table '{table_name}'"),
            )
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting HC profile for table: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")
