"""
Database utility functions for HC Column Profiles.
Follows the same pattern as column_description_db_utils.py.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import attributes
from sqlmodel import select

from agent.db_utils.database_db_utils import get_primary_db_id
from knowledge.services.logger import logger
from knowledge.services.sqlmodel_session import get_async_session
from models.sql_models import HCColumnProfiles

_LOW_CARD_LABEL = "LOW_CARDINALITY_CATEGORICAL"
_HC_TEXT_SEARCH_LABEL = "HIGH_CARDINALITY_TEXT_SEARCH"


async def save_hc_column_profiles(
    agent_id: str, table_name: str, profiles: dict, db_id: Optional[str] = None
) -> dict:
    """Upsert column profiles for a single table (scoped to db_id)."""
    try:
        db_id = db_id or await get_primary_db_id(agent_id)
        async for session in get_async_session():
            res = await session.execute(
                select(HCColumnProfiles).where(
                    HCColumnProfiles.agent_id == agent_id,
                    HCColumnProfiles.db_id == db_id,
                    HCColumnProfiles.table_name == table_name,
                )
            )
            record = res.scalars().first()

            if record:
                record.column_profiles = dict(profiles)
                record.updated_at = datetime.utcnow()
                attributes.flag_modified(record, "column_profiles")
            else:
                record = HCColumnProfiles(
                    chatbot_id=agent_id,
                    agent_id=agent_id,
                    db_id=db_id,
                    table_name=table_name,
                    column_profiles=profiles,
                    profiled_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )
                session.add(record)

            await session.commit()
            logger.info(f"[HC Profile DB] Saved profiles for table '{table_name}', agent_id={agent_id}, db_id={db_id}")
            return {"message": "HC column profiles saved successfully", "status": True}
    except Exception as e:
        logger.error(f"Exception in save_hc_column_profiles: {e}")
        return {"message": f"Error in save_hc_column_profiles: {e}", "status": False}


async def get_hc_column_profiles(
    agent_id: str, table_name: str, db_id: Optional[str] = None
) -> dict:
    """Get profiles for a specific table (scoped to db_id)."""
    try:
        db_id = db_id or await get_primary_db_id(agent_id)
        async for session in get_async_session():
            res = await session.execute(
                select(HCColumnProfiles).where(
                    HCColumnProfiles.agent_id == agent_id,
                    HCColumnProfiles.db_id == db_id,
                    HCColumnProfiles.table_name == table_name,
                )
            )
            record = res.scalars().first()

            if record:
                return {
                    "record": {
                        "table_name": record.table_name,
                        "column_profiles": record.column_profiles,
                        "profiled_at": record.profiled_at,
                        "updated_at": record.updated_at,
                    },
                    "message": "HC column profiles retrieved successfully",
                    "status": True,
                }
            return {
                "record": None,
                "message": f"No HC profiles found for table '{table_name}'",
                "status": False,
            }
    except Exception as e:
        logger.error(f"Exception in get_hc_column_profiles: {e}")
        return {"message": f"Error in get_hc_column_profiles: {e}", "status": False}


async def get_all_hc_column_profiles(agent_id: str, db_id: Optional[str] = None) -> dict:
    """Get profiles for all profiled tables of an agent (scoped to db_id)."""
    try:
        db_id = db_id or await get_primary_db_id(agent_id)
        async for session in get_async_session():
            res = await session.execute(
                select(HCColumnProfiles).where(
                    HCColumnProfiles.agent_id == agent_id,
                    HCColumnProfiles.db_id == db_id,
                )
            )
            records = res.scalars().all()

            records_list = [
                {
                    "table_name": r.table_name,
                    "column_profiles": r.column_profiles,
                    "profiled_at": r.profiled_at,
                    "updated_at": r.updated_at,
                }
                for r in records
            ]
            return {
                "records": records_list,
                "message": f"Found {len(records_list)} table profile(s)",
                "status": True,
            }
    except Exception as e:
        logger.error(f"Exception in get_all_hc_column_profiles: {e}")
        return {"message": f"Error in get_all_hc_column_profiles: {e}", "status": False}


async def get_low_cardinality_columns(agent_id: str, db_id: Optional[str] = None) -> dict:
    """
    Return a dict of {table_name: {col_name: [values]}} for all
    LOW_CARDINALITY_CATEGORICAL columns across all profiled tables (scoped to db_id).
    Used by the SQL gen pipeline to inject valid values into prompts.
    """
    try:
        db_id = db_id or await get_primary_db_id(agent_id)
        async for session in get_async_session():
            res = await session.execute(
                select(HCColumnProfiles).where(
                    HCColumnProfiles.agent_id == agent_id,
                    HCColumnProfiles.db_id == db_id,
                )
            )
            records = res.scalars().all()

            result: dict = {}
            for r in records:
                profiles = r.column_profiles or {}
                low_card_cols: dict = {}
                for col_name, profile in profiles.items():
                    if (
                        isinstance(profile, dict)
                        and profile.get("classification") == _LOW_CARD_LABEL
                        and profile.get("sample_values")
                    ):
                        low_card_cols[col_name] = profile["sample_values"]
                if low_card_cols:
                    result[r.table_name] = low_card_cols

            return result
    except Exception as e:
        logger.error(f"Exception in get_low_cardinality_columns: {e}")
        return {}


async def get_hc_text_search_samples(agent_id: str, db_id: Optional[str] = None) -> dict:
    """
    Return {table_name: {col_name: [sample_values]}} for all HIGH_CARDINALITY_TEXT_SEARCH columns (scoped to db_id).
    Used to enrich entity extraction context so the LLM knows what is stored in each column.
    """
    try:
        db_id = db_id or await get_primary_db_id(agent_id)
        async for session in get_async_session():
            res = await session.execute(
                select(HCColumnProfiles).where(
                    HCColumnProfiles.agent_id == agent_id,
                    HCColumnProfiles.db_id == db_id,
                )
            )
            records = res.scalars().all()

            result: dict = {}
            for r in records:
                profiles = r.column_profiles or {}
                col_samples: dict = {}
                for col_name, profile in profiles.items():
                    if (
                        isinstance(profile, dict)
                        and profile.get("classification") == _HC_TEXT_SEARCH_LABEL
                        and profile.get("sample_values")
                    ):
                        col_samples[col_name] = profile["sample_values"]
                if col_samples:
                    result[r.table_name] = col_samples
            return result
    except Exception as e:
        logger.error(f"Exception in get_hc_text_search_samples: {e}")
        return {}


async def get_hc_text_search_columns(agent_id: str, db_id: Optional[str] = None) -> dict:
    """
    Return {table_name: [col_name, ...]} for all HIGH_CARDINALITY_TEXT_SEARCH columns (scoped to db_id).
    Used by the SQL gen pipeline to drive Qdrant semantic search.
    """
    try:
        db_id = db_id or await get_primary_db_id(agent_id)
        async for session in get_async_session():
            res = await session.execute(
                select(HCColumnProfiles).where(
                    HCColumnProfiles.agent_id == agent_id,
                    HCColumnProfiles.db_id == db_id,
                )
            )
            records = res.scalars().all()

            result: dict = {}
            for r in records:
                profiles = r.column_profiles or {}
                hc_cols = [
                    col_name
                    for col_name, profile in profiles.items()
                    if isinstance(profile, dict)
                    and profile.get("classification") == _HC_TEXT_SEARCH_LABEL
                ]
                if hc_cols:
                    result[r.table_name] = hc_cols
            return result
    except Exception as e:
        logger.error(f"Exception in get_hc_text_search_columns: {e}")
        return {}


async def delete_hc_column_profiles(
    agent_id: str, table_name: Optional[str] = None, db_id: Optional[str] = None
) -> dict:
    """Delete profiles for one table or all tables of an agent (scoped to db_id)."""
    try:
        db_id = db_id or await get_primary_db_id(agent_id)
        async for session in get_async_session():
            query = select(HCColumnProfiles).where(
                HCColumnProfiles.agent_id == agent_id,
                HCColumnProfiles.db_id == db_id,
            )
            if table_name:
                query = query.where(HCColumnProfiles.table_name == table_name)

            res = await session.execute(query)
            records = res.scalars().all()

            if not records:
                return {"message": "No HC profiles found to delete", "status": False}

            for r in records:
                await session.delete(r)
            await session.commit()

            label = f"table '{table_name}'" if table_name else "all tables"
            logger.info(f"[HC Profile DB] Deleted profiles for {label}, agent_id={agent_id}, db_id={db_id}")
            return {
                "message": f"HC column profiles deleted for {label}",
                "status": True,
                "deleted_count": len(records),
            }
    except Exception as e:
        logger.error(f"Exception in delete_hc_column_profiles: {e}")
        return {"message": f"Error in delete_hc_column_profiles: {e}", "status": False}
