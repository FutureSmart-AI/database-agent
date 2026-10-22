"""
RESTful API endpoints for HC Column Profiling.

Resource: hc-profile — automatically detected and classified column profiles.

Routes:
  POST   /v1/agents/{agent_id}/tables/hc-profile
  GET    /v1/agents/{agent_id}/tables/hc-profile
  DELETE /v1/agents/{agent_id}/tables/hc-profile
  GET    /v1/agents/{agent_id}/tables/{table_name}/hc-profile
  DELETE /v1/agents/{agent_id}/tables/{table_name}/hc-profile
"""
import asyncio
import json
import traceback
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, Body, Depends, HTTPException, Path
from starlette.requests import Request

from sqlmodel import select

from agent.utils.authorization import require_agent_permission
from agent.utils.hc_column_profiler import (
    HIGH_CARDINALITY_TEXT_SEARCH,
    ProfilingConfig,
    profile_all_tables,
)
from api.v1.schemas.hc_profile import TriggerHCProfileRequest
from chatbot_management.services.sqlmodel_session import get_async_session
from chatbot_management.utils.api_validation import get_api_key_or_session
from knowledge.db_utils import database_db_utils, table_description_db_utils
from knowledge.db_utils.hc_profile_db_utils import (
    delete_hc_column_profiles,
    get_all_hc_column_profiles,
    get_hc_column_profiles,
    save_hc_column_profiles,
)
from logger import logger
from models.sql_models import ChatbotDetails


async def _get_agent(agent_id: str):
    """Return ChatbotDetails or None — mirrors the pattern used in database.py."""
    async for session in get_async_session():
        result = await session.execute(
            select(ChatbotDetails).where(ChatbotDetails.agent_id == agent_id)
        )
        return result.scalar_one_or_none()

router = APIRouter(prefix="/v1")


# ---------------------------------------------------------------------------
# Business logic
# ---------------------------------------------------------------------------

async def run_hc_profile_for_agent(
    user_id: str, agent_id: str, body: TriggerHCProfileRequest, db_id: Optional[str] = None
) -> dict:
    logger.info(f"[HC Profile] Step 1/5: verifying agent {agent_id} exists")
    agent = await _get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    # Multi-DB: resolve the agent's primary db when no explicit db_id is supplied.
    if db_id is None:
        db_id = await database_db_utils.get_primary_db_id(agent_id)

    logger.info(f"[HC Profile] Step 2/5: fetching DB connection for agent {agent_id} (db_id={db_id})")
    if db_id:
        db_resp = await database_db_utils.get_db_connection_by_id(agent_id, db_id)
    else:
        db_resp = await database_db_utils.get_db_connection(None, agent_id)
    if not db_resp.get("status") or not db_resp.get("db_details"):
        raise HTTPException(
            status_code=400,
            detail="Database connection not found for this agent",
        )
    db_details = db_resp["db_details"]
    logger.info(f"[HC Profile] Step 3/5: DB connection retrieved, building profiling config")

    cfg_req = body.config
    config = ProfilingConfig(
        **{
            k: v
            for k, v in (
                {
                    "low_cardinality_threshold": cfg_req.low_cardinality_threshold,
                    "high_null_threshold": cfg_req.high_null_threshold,
                    "min_avg_text_len_for_hc": cfg_req.min_avg_text_len_for_hc,
                    "sample_limit": cfg_req.sample_limit,
                }
                if cfg_req
                else {}
            ).items()
            if v is not None
        }
    )

    table_names: Optional[List[str]] = body.tables or None
    logger.info(f"[HC Profile] Step 4/5: running profiler (tables={table_names or 'all'})")
    profiles_by_table: Dict[str, dict] = await asyncio.to_thread(
        profile_all_tables, db_details, config, table_names
    )
    logger.info(f"[HC Profile] Profiling complete: {len(profiles_by_table)} tables. Persisting...")

    failed_tables = []
    for table_name, profiles in profiles_by_table.items():
        result = await save_hc_column_profiles(agent_id, table_name, profiles, db_id=db_id)
        if not result.get("status"):
            failed_tables.append(table_name)
            logger.error(f"[HC Profile] Failed to persist profiles for table '{table_name}': {result.get('message')}")

    if failed_tables:
        raise HTTPException(
            status_code=500,
            detail="Profiling completed but failed to persist results. Please try again.",
        )
    logger.info(f"[HC Profile] Step 5/5: profiles persisted for {len(profiles_by_table)} tables")

    classification_counts: Dict[str, int] = {}
    total_columns = 0
    for profiles in profiles_by_table.values():
        for col_profile in profiles.values():
            label = col_profile.get("classification", "NORMAL_COLUMN")
            classification_counts[label] = classification_counts.get(label, 0) + 1
            total_columns += 1

    hc_registered: List[Dict] = []
    if body.auto_register_hc:
        try:
            hc_registered = await _auto_register_hc_columns(
                agent_id, user_id, db_details, profiles_by_table, db_id=db_id
            )
        except Exception as e:
            logger.warning(
                f"[HC Profile] Auto-registration of HC columns failed (non-blocking): {e}"
            )

    return {
        "status": "success",
        "tables_profiled": len(profiles_by_table),
        "total_columns": total_columns,
        "classification_counts": classification_counts,
        "hc_columns_auto_registered": hc_registered,
        "message": "HC column profiling completed successfully",
    }


async def _auto_register_hc_columns(
    agent_id: str,
    user_id: str,
    db_details: dict,
    profiles_by_table: Dict[str, dict],
    db_id: Optional[str] = None,
) -> List[Dict]:
    """
    For every HIGH_CARDINALITY_TEXT_SEARCH column found in profiles:
      1. Index its values into Qdrant
      2. Merge it into TableDescription.high_cardinality_columns
    Returns list of {table_name, column_name} dicts that were registered.
    """
    from agent.utils.high_cardinality_qdrant_utils import get_cardinality_store

    hc_pairs: List[Tuple[str, str]] = []
    for table_name, profiles in profiles_by_table.items():
        for col_name, profile in profiles.items():
            if profile.get("classification") == HIGH_CARDINALITY_TEXT_SEARCH:
                hc_pairs.append((table_name, col_name))

    if not hc_pairs:
        return []

    store = await get_cardinality_store()
    qdrant_loaded: List[Tuple[str, str]] = []
    try:
        for table_name, col_name in hc_pairs:
            unique_values_dict = table_description_db_utils.get_unique_values_for_columns(
                {"db_details": db_details}, table_name, [col_name]
            )
            values = [str(v) for v in unique_values_dict.get(col_name, []) if v is not None]
            if values:
                await store.store_values(
                    values=values,
                    metadata={"table": table_name, "column": col_name, "db_id": db_id},
                )
                qdrant_loaded.append((table_name, col_name))
                logger.info(
                    f"[HC Profile] Indexed {len(values)} values into Qdrant for {table_name}.{col_name}"
                )
    except Exception as qdrant_err:
        for t, c in qdrant_loaded:
            try:
                await store.delete_values_for_table_column(t, c, db_id=db_id)
            except Exception:
                pass
        raise RuntimeError(f"Qdrant indexing failed: {qdrant_err}") from qdrant_err

    return [{"table_name": t, "column_name": c} for t, c in hc_pairs]


# ---------------------------------------------------------------------------
# Delete side-effect helper
# ---------------------------------------------------------------------------

async def _cleanup_qdrant_for_profiles(records: List[Dict], db_id: Optional[str] = None) -> None:
    """Delete Qdrant vectors for every HIGH_CARDINALITY_TEXT_SEARCH column in the given profile records.

    Vector cleanup is best-effort: only HIGH_CARDINALITY_TEXT_SEARCH columns have vectors, so the
    store is built lazily (never when there is nothing to clean), and a Qdrant outage or missing
    config degrades to a warning. Deleting the stored profile rows must not depend on Qdrant being
    reachable — otherwise a config gap turns the DELETE endpoints into a 500.
    """
    from agent.utils.high_cardinality_qdrant_utils import get_cardinality_store

    targets = [
        (record.get("table_name"), col_name)
        for record in records
        for col_name, profile in (record.get("column_profiles") or {}).items()
        if isinstance(profile, dict) and profile.get("classification") == HIGH_CARDINALITY_TEXT_SEARCH
    ]
    if not targets:
        return

    try:
        store = await get_cardinality_store()
    except Exception as e:
        logger.warning(f"[HC Delete] Qdrant unavailable ({e}); skipping vector cleanup")
        return

    for tname, col_name in targets:
        try:
            await store.delete_values_for_table_column(tname, col_name, db_id=db_id)
            logger.info(f"[HC Delete] Removed Qdrant vectors for {tname}.{col_name}")
        except Exception as e:
            logger.warning(f"[HC Delete] Failed to remove Qdrant vectors for {tname}.{col_name}: {e}")


# ---------------------------------------------------------------------------
# Collection endpoints  (all tables)
# ---------------------------------------------------------------------------

@router.post(
    "/agents/{agent_id}/tables/hc-profile",
    tags=["HC Column Profiling"],
)
async def trigger_hc_profile(
    agent_id: str = Path(..., description="Agent ID"),
    body: TriggerHCProfileRequest = Body(default=TriggerHCProfileRequest()),
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("write")),
    db_id: Optional[str] = None,
):
    """
    Trigger automatic profiling of all (or specified) database tables.

    Classifies every column into one of:
    - `LOW_CARDINALITY_CATEGORICAL` — text/int with ≤ threshold distinct values
    - `HIGH_CARDINALITY_TEXT_SEARCH` — text with many distinct values
    - `NORMAL_COLUMN` — numerics, dates, identifiers
    - `IGNORE` — audit columns, near-empty, non-queryable types

    When `auto_register_hc` is `true` (default), `HIGH_CARDINALITY_TEXT_SEARCH`
    columns are automatically indexed into Qdrant and registered in the agent's
    high-cardinality column configuration.
    """
    try:
        user_id = auth.get("user_id")
        logger.info(f"Triggering HC profile for agent {agent_id} | user_id={user_id} | db_id={db_id}")
        result = await run_hc_profile_for_agent(user_id, agent_id, body, db_id=db_id)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error triggering HC profile: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")


@router.get(
    "/agents/{agent_id}/tables/hc-profile",
    tags=["HC Column Profiling"],
)
async def get_all_hc_profiles(
    agent_id: str = Path(..., description="Agent ID"),
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("use")),
    db_id: Optional[str] = None,
):
    """
    Get stored HC column profiles for all profiled tables of an agent.
    """
    try:
        user_id = auth.get("user_id")
        logger.info(f"Getting all HC profiles for agent {agent_id} (db_id={db_id})")
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
    "/agents/{agent_id}/tables/hc-profile",
    tags=["HC Column Profiling"],
)
async def delete_all_hc_profiles(
    agent_id: str = Path(..., description="Agent ID"),
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("write")),
    db_id: Optional[str] = None,
):
    """
    Delete all stored HC column profiles for an agent.
    Also removes Qdrant vectors for all HIGH_CARDINALITY_TEXT_SEARCH columns.
    """
    try:
        logger.info(f"Deleting all HC profiles for agent {agent_id} (db_id={db_id})")
        agent = await _get_agent(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
        if db_id is None:
            db_id = await database_db_utils.get_primary_db_id(agent_id)
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


# ---------------------------------------------------------------------------
# Individual table endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/agents/{agent_id}/tables/{table_name}/hc-profile",
    tags=["HC Column Profiling"],
)
async def get_table_hc_profile(
    agent_id: str = Path(..., description="Agent ID"),
    table_name: str = Path(..., description="Table name"),
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("use")),
    db_id: Optional[str] = None,
):
    """
    Get the stored HC column profile for a specific table.
    """
    try:
        user_id = auth.get("user_id")
        logger.info(f"Getting HC profile for table {table_name} in agent {agent_id} (db_id={db_id})")
        agent = await _get_agent(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
        result = await get_hc_column_profiles(agent_id, table_name, db_id=db_id)
        if not result.get("status"):
            raise HTTPException(
                status_code=404,
                detail=f"No HC profile found for table '{table_name}'",
            )
        return {"data": result["record"]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting HC profile for table: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")


@router.delete(
    "/agents/{agent_id}/tables/{table_name}/hc-profile",
    tags=["HC Column Profiling"],
)
async def delete_table_hc_profile(
    agent_id: str = Path(..., description="Agent ID"),
    table_name: str = Path(..., description="Table name"),
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("write")),
    db_id: Optional[str] = None,
):
    """
    Delete the stored HC column profile for a specific table.
    Also removes Qdrant vectors for all HIGH_CARDINALITY_TEXT_SEARCH columns in that table.
    """
    try:
        logger.info(f"Deleting HC profile for table {table_name} in agent {agent_id} (db_id={db_id})")
        agent = await _get_agent(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
        if db_id is None:
            db_id = await database_db_utils.get_primary_db_id(agent_id)
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
