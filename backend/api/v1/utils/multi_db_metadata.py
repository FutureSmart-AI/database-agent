"""
Cascade cleanup of per-DB metadata when a database is deleted (multi-db-spec.md §8.1).
Deletes the Postgres rows scoped to (agent_id, db_id) and best-effort removes the matching
Qdrant points (few-shot + high-cardinality) tagged with that db_id.
"""
from chatbot_management.services.logger import logger
from chatbot_management.services.sqlmodel_session import get_async_session
from models.sql_models import (
    TableDescription, ColumnDescription, HCColumnProfiles, FewShotExamples,
)
from sqlmodel import select


async def purge_database_metadata(agent_id: str, db_id: str) -> None:
    """Delete all metadata rows + vectors scoped to (agent_id, db_id). Best-effort."""
    # ── Postgres rows (source of truth) ──
    async for session in get_async_session():
        for model in (TableDescription, ColumnDescription, HCColumnProfiles, FewShotExamples):
            try:
                res = await session.execute(select(model).where(model.db_id == db_id))
                for row in res.scalars().all():
                    await session.delete(row)
            except Exception as e:
                logger.warning(f"[purge_db_metadata] {model.__name__} delete failed for {db_id}: {e}")
        await session.commit()

    # ── Qdrant: few-shot examples for this db_id ──
    try:
        from qdrant_client import models as qmodels
        from agent.utils.few_shot_utils import get_few_shot_service
        fs = await get_few_shot_service()
        store = getattr(fs, "store", None) or getattr(fs, "_store", None)
        client = getattr(store, "client", None)
        collection = getattr(store, "collection_name", None) or "few-shot-examples"
        if client is not None:
            await client.delete(
                collection_name=collection,
                points_selector=qmodels.FilterSelector(filter=qmodels.Filter(must=[
                    qmodels.FieldCondition(key="agent_id", match=qmodels.MatchValue(value=agent_id)),
                    qmodels.FieldCondition(key="db_id", match=qmodels.MatchValue(value=db_id)),
                ])),
            )
    except Exception as e:
        logger.warning(f"[purge_db_metadata] few-shot Qdrant cleanup skipped for {db_id}: {e}")

    # ── Qdrant: high-cardinality values for this db_id ──
    # NOTE: HC points are stored with only value/table/column/db_id — they carry
    # NO agent_id payload (unlike few-shot). Filtering on agent_id here matched
    # zero points, so every deleted DB used to leak all its HC vectors. db_id is
    # globally unique, so scoping by db_id alone is both correct and sufficient.
    try:
        from qdrant_client import models as qmodels
        from agent.utils.high_cardinality_qdrant_utils import get_cardinality_store
        hc_store = await get_cardinality_store()
        client = getattr(hc_store, "client", None)
        collection = getattr(hc_store, "collection_name", None) or "high-cardinality-values"
        if client is not None:
            await client.delete(
                collection_name=collection,
                points_selector=qmodels.FilterSelector(filter=qmodels.Filter(must=[
                    qmodels.FieldCondition(key="db_id", match=qmodels.MatchValue(value=db_id)),
                ])),
            )
    except Exception as e:
        logger.warning(f"[purge_db_metadata] HC Qdrant cleanup skipped for {db_id}: {e}")
