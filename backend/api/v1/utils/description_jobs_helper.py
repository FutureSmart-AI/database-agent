from agent.utils.model_profiles import response_text
"""
Async auto-generate-description jobs (multi-db-spec.md §6).

POST .../description/generate creates a `description_generation_jobs` row (status=running),
spawns a background task that inspects the DB + calls an LLM, and returns {job_id, status}.
The UI polls GET .../description/generate/{job_id} until done|failed. Job state lives in
Postgres so polling is correct across multiple workers.
"""
import asyncio
import uuid
from datetime import datetime
from typing import Optional, Set, Dict, Any, List

from fastapi import HTTPException

from chatbot_management.services.logger import logger
from chatbot_management.services.sqlmodel_session import get_async_session
from models.sql_models import DescriptionGenerationJobs
from sqlmodel import select

from agent.db_utils.database_db_utils import get_db_connection_by_id

# Strong refs so background tasks aren't GC'd before completion (same pattern as database.py).
_jobs: Set[asyncio.Task] = set()

_MAX_TABLES = 30          # cap tables inspected for latency
_SAMPLE_TABLES = 10       # tables we sample rows from
_SAMPLE_ROWS = 3


def _generate_job_id() -> str:
    return f"JOB_{str(uuid.uuid4()).split('-')[0]}".upper()


async def start_description_job(agent_id: str, db_id: str, apply_to_db: bool = False,
                                overwrite: bool = False) -> Dict[str, Any]:
    """Create a job row + launch the background generation task.

    apply_to_db=True → on completion the generated description is written onto the connection
    (source='auto') and the DB is activated. Used by both the auto-on-add flow and the explicit
    Generate endpoint, so the result lands on the DB without a separate save step.
    overwrite=True → replace an existing description too (explicit Generate). When False
    (auto-on-add), a description set in the meantime is left untouched.
    """
    conn = await get_db_connection_by_id(agent_id, db_id)
    if not conn.get("status") or not conn.get("db_details"):
        raise HTTPException(status_code=404, detail=f"Database {db_id} not found for agent {agent_id}")

    job_id = _generate_job_id()
    async for session in get_async_session():
        session.add(DescriptionGenerationJobs(
            job_id=job_id, agent_id=agent_id, db_id=db_id, status="running",
            created_at=datetime.utcnow(), updated_at=datetime.utcnow(),
        ))
        await session.commit()

    task = asyncio.create_task(_run_generation(agent_id, db_id, job_id, conn["db_details"],
                                               apply_to_db=apply_to_db, overwrite=overwrite))
    _jobs.add(task)
    task.add_done_callback(_jobs.discard)
    return {"job_id": job_id, "status": "running"}


async def get_description_job(agent_id: str, db_id: str, job_id: str) -> Dict[str, Any]:
    async for session in get_async_session():
        res = await session.execute(
            select(DescriptionGenerationJobs).where(
                DescriptionGenerationJobs.job_id == job_id,
                DescriptionGenerationJobs.agent_id == agent_id,
                DescriptionGenerationJobs.db_id == db_id,
            )
        )
        job = res.scalar_one_or_none()
        if not job:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        return {"status": job.status, "description": job.description, "error": job.error}


async def _set_job(job_id: str, **fields) -> None:
    async for session in get_async_session():
        res = await session.execute(
            select(DescriptionGenerationJobs).where(DescriptionGenerationJobs.job_id == job_id)
        )
        job = res.scalar_one_or_none()
        if job:
            for k, v in fields.items():
                setattr(job, k, v)
            job.updated_at = datetime.utcnow()
            session.add(job)
            await session.commit()


def _inspect_schema_sync(db_details: Dict[str, Any]) -> str:
    """Build a compact schema+samples text for the LLM. Runs in a thread."""
    from api.v1.utils.columns_helper import get_table_columns_from_db
    from knowledge.db_utils.table_description_db_utils import get_table_names_from_db, get_unique_values_for_columns

    tables: List[str] = get_table_names_from_db({"db_details": db_details}) or []
    tables = tables[:_MAX_TABLES]
    lines: List[str] = []
    for i, t in enumerate(tables):
        try:
            cols = get_table_columns_from_db(db_details, t)
        except Exception:
            cols = []
        col_str = ", ".join(f"{c['column_name']}:{c['data_type']}" for c in cols) if cols else "?"
        lines.append(f"- {t} ({col_str})")
        if i < _SAMPLE_TABLES and cols:
            try:
                first_col = cols[0]["column_name"]
                samples = get_unique_values_for_columns({"db_details": db_details}, t, [first_col],
                                                        limit=_SAMPLE_ROWS)
                vals = samples.get(first_col, [])[:_SAMPLE_ROWS]
                if vals:
                    lines.append(f"    sample {first_col}: {', '.join(str(v) for v in vals)}")
            except Exception:
                pass
    return "\n".join(lines)


async def _build_llm(agent_id: str):
    """The description model, paid for by the AGENT OWNER's key policy.

    Setup runs outside any chat request, so nothing else binds the owner here: without the
    owner's key a bring-your-own-key workspace would have its setup billed to the platform.
    A missing or invalid key raises a ProviderCredentialError whose message the job records.
    """
    from agent.utils.model_profiles import operation_config, build_chat_model
    from agent.utils.owner_credential_utils import get_owner_api_key_for_provider
    from chatbot_management.db_utils.bot_crud_db_utils import get_owner_email_by_agent_id

    conf = operation_config("descriptions.default")
    owner_id = await get_owner_email_by_agent_id(agent_id)
    api_key = await get_owner_api_key_for_provider(owner_id, conf["provider"])
    return build_chat_model(conf, api_key=api_key)


async def _apply_description_to_db(agent_id: str, db_id: str, description: str,
                                   overwrite: bool = False) -> None:
    """Apply a generated description to the DB row and activate it, so the result lands on the
    connection (otherwise it stays only in the job row and the DB stays unroutable).
    overwrite=False keeps a description set in the meantime (auto-on-add race); overwrite=True
    replaces it (explicit Generate, where the user asked for a fresh one)."""
    from models.sql_models import ChatbotConnection
    async for session in get_async_session():
        # Filter tombstones: this reactivates the row (is_active=True), so a DB deleted while
        # its description job was still running must not come back to life.
        res = await session.execute(select(ChatbotConnection).where(
            ChatbotConnection.db_id == db_id,
            ChatbotConnection.deleted == False,  # noqa: E712
        ))
        conn = res.scalar_one_or_none()
        if conn and (overwrite or not (conn.description or "").strip()):
            conn.description = description
            conn.description_source = "auto"
            conn.description_updated_at = datetime.utcnow()
            conn.is_active = True
            conn.updated_at = datetime.utcnow()
            session.add(conn)
            await session.commit()


async def _run_generation(agent_id: str, db_id: str, job_id: str, db_details: Dict[str, Any],
                          apply_to_db: bool = False, overwrite: bool = False) -> None:
    try:
        from agent.utils.heavy_work_gate import heavy_work
        async with heavy_work(f"desc-job {job_id} agent={agent_id} db={db_id}"):
            schema_text = await asyncio.to_thread(_inspect_schema_sync, db_details)
        prompt = (
            "Write a concise description of this database that will be used to ROUTE "
            "natural-language questions to the correct database among several. For routing to "
            "work, the description must make THIS database's DISTINCTIVE, authoritative data "
            "clear — i.e. what kinds of questions it (and not some other database) should answer.\n\n"
            "Guidelines:\n"
            "- Lead with the database's core purpose / the domain it is the source of truth for.\n"
            "- Then state the specific KINDS OF QUESTIONS it can answer — the concrete entities, "
            "metrics, and facts it holds (e.g. 'per-request latency, cost and token usage', "
            "'which services an agent is linked to', 'document processing status').\n"
            "- Name the important entities/data concisely; do NOT list every table.\n"
            "- Be DISTINCTIVE, not generic: avoid vague phrasing like 'the core data store for a "
            "platform' that could describe almost any database — that hurts routing.\n"
            "- 2-4 sentences, no preamble.\n\n"
            f"Database name: {db_details.get('db_name')}\n"
            f"Tables and columns:\n{schema_text}\n\nDescription:"
        )
        llm = await _build_llm(agent_id)
        resp = await llm.ainvoke(prompt)
        description = response_text(resp)
        await _set_job(job_id, status="done", description=description)
        if apply_to_db and description:
            await _apply_description_to_db(agent_id, db_id, description, overwrite=overwrite)
        logger.info(f"[desc-job] {job_id} done for agent={agent_id} db={db_id} (applied={apply_to_db})")
    except Exception as e:
        logger.error(f"[desc-job] {job_id} failed: {e}")
        await _set_job(job_id, status="failed", error=str(e))


# ── Table-description generation ────────────────────────────────────────────────
# Reuses the description_generation_jobs table; a "TBLDESC_" job-id prefix distinguishes these
# from the DB-level routing-description jobs (so no schema change is needed and the DB-level
# status query filters them out — see databases_helper._latest_job_status_by_db).
_TABLE_JOB_PREFIX = "TBLDESC_"
_TABLE_GEN_CONCURRENCY = 6
_TABLE_PROMPT_INTRO = (
    "Write a concise 1-2 sentence description of this SQL table: what each row represents and "
    "the data it holds, stated as plain facts. Name key columns only where useful. No preamble, "
    "no markdown.\n\n"
)


def _generate_table_job_id() -> str:
    return f"{_TABLE_JOB_PREFIX}{str(uuid.uuid4()).split('-')[0]}".upper()


async def start_table_description_job(agent_id: str, db_id: str, overwrite: bool = False) -> Dict[str, Any]:
    """Create a job row + launch background generation of a description for EVERY table in the DB.

    overwrite=False (default) only fills tables whose description is currently blank, preserving
    any manually-set ones; overwrite=True regenerates all. Results are saved onto the per-DB
    table-description record (scoped by db_id), so the UI's table list shows them immediately.
    """
    conn = await get_db_connection_by_id(agent_id, db_id)
    if not conn.get("status") or not conn.get("db_details"):
        raise HTTPException(status_code=404, detail=f"Database {db_id} not found for agent {agent_id}")

    job_id = _generate_table_job_id()
    async for session in get_async_session():
        session.add(DescriptionGenerationJobs(
            job_id=job_id, agent_id=agent_id, db_id=db_id, status="running",
            created_at=datetime.utcnow(), updated_at=datetime.utcnow(),
        ))
        await session.commit()

    task = asyncio.create_task(_run_table_generation(agent_id, db_id, job_id, conn["db_details"], overwrite=overwrite))
    _jobs.add(task)
    task.add_done_callback(_jobs.discard)
    return {"job_id": job_id, "status": "running"}


async def get_table_description_job(agent_id: str, db_id: str, job_id: str) -> Dict[str, Any]:
    async for session in get_async_session():
        res = await session.execute(
            select(DescriptionGenerationJobs).where(
                DescriptionGenerationJobs.job_id == job_id,
                DescriptionGenerationJobs.agent_id == agent_id,
                DescriptionGenerationJobs.db_id == db_id,
            )
        )
        job = res.scalar_one_or_none()
        if not job:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        # `description` holds a human summary for table jobs (not a single description).
        return {"status": job.status, "message": job.description, "error": job.error}


async def _run_table_generation(agent_id: str, db_id: str, job_id: str, db_details: Dict[str, Any],
                                overwrite: bool = False) -> None:
    try:
        from agent.utils.heavy_work_gate import heavy_work
        from api.v1.utils.columns_helper import get_table_columns_from_db
        from api.v1.utils.tables_helper import get_all_agent_table_descriptions
        from knowledge.db_utils.table_description_db_utils import get_table_names_from_db
        from knowledge.db_utils import table_description_db_utils

        existing_rows = await get_all_agent_table_descriptions(agent_id, db_id=db_id)
        existing = {r["table_name"]: (r.get("description") or "") for r in existing_rows}

        def _introspect():
            tables = get_table_names_from_db({"db_details": db_details}) or []
            schema = {}
            for t in tables:
                try:
                    schema[t] = get_table_columns_from_db(db_details, t)
                except Exception:
                    schema[t] = []
            return tables, schema

        async with heavy_work(f"tbl-desc-job {job_id} agent={agent_id} db={db_id}"):
            tables, schema = await asyncio.to_thread(_introspect)
        if not tables:
            await _set_job(job_id, status="failed", error="No tables found in this database")
            return

        llm = await _build_llm(agent_id)
        sem = asyncio.Semaphore(_TABLE_GEN_CONCURRENCY)

        async def _gen_one(table: str):
            current = (existing.get(table) or "").strip()
            if current and not overwrite:
                return table, current  # preserve existing (only fill blanks)
            cols = schema.get(table) or []
            col_str = ", ".join(f"{c.get('column_name')}:{c.get('data_type')}" for c in cols) or "?"
            prompt = (
                _TABLE_PROMPT_INTRO +
                f"Database: {db_details.get('db_name')}\nTable: {table}\nColumns: {col_str}\n\nDescription:"
            )
            async with sem:
                try:
                    resp = await llm.ainvoke(prompt)
                    return table, response_text(resp)
                except Exception as e:
                    logger.warning(f"[tbl-desc-job] {job_id} table={table} generation failed: {e}")
                    return table, current  # keep whatever was there on failure

        generated = dict(await asyncio.gather(*[_gen_one(t) for t in tables]))

        # Save descriptions for ALL tables (blank string for any that produced nothing). The
        # record is re-read under a lock and anything written while the model was running is
        # kept, with the stored include/exclude flags (DA-DESC-RACE-001).
        db_res = await table_description_db_utils.save_generated_table_descriptions(
            agent_id, db_id, existing, generated, tables
        )
        if not (db_res and db_res.get("status")):
            await _set_job(job_id, status="failed", error="Failed to save generated table descriptions")
            return

        filled = sum(1 for t in tables if (generated.get(t) or "").strip())
        await _set_job(job_id, status="done",
                       description=f"Generated descriptions for {filled}/{len(tables)} tables")
        logger.info(f"[tbl-desc-job] {job_id} done for agent={agent_id} db={db_id} "
                    f"filled={filled}/{len(tables)} overwrite={overwrite}")
    except Exception as e:
        logger.error(f"[tbl-desc-job] {job_id} failed: {e}")
        await _set_job(job_id, status="failed", error=str(e))


async def generate_single_table_description(agent_id: str, db_id: str, table_name: str) -> Dict[str, Any]:
    """Synchronously auto-generate + save a description for ONE table (LLM), returning the text.

    Unlike the whole-DB job this runs inline (a single LLM call is fast) and returns the result
    directly — no polling. Only the target table's description is changed; every other table and
    all include/exclude flags are preserved.
    """
    import json
    conn = await get_db_connection_by_id(agent_id, db_id)
    if not conn.get("status") or not conn.get("db_details"):
        raise HTTPException(status_code=404, detail=f"Database {db_id} not found for agent {agent_id}")
    db_details = conn["db_details"]

    from api.v1.utils.columns_helper import get_table_columns_from_db
    from knowledge.db_utils.table_description_db_utils import get_table_names_from_db
    from knowledge.db_utils import table_description_db_utils

    def _introspect():
        tables = get_table_names_from_db({"db_details": db_details}) or []
        if table_name not in tables:
            return None
        try:
            return get_table_columns_from_db(db_details, table_name)
        except Exception:
            return []

    cols = await asyncio.to_thread(_introspect)
    if cols is None:
        raise HTTPException(status_code=404, detail=f"Table '{table_name}' not found in database {db_id}")

    col_str = ", ".join(f"{c.get('column_name')}:{c.get('data_type')}" for c in cols) or "?"
    prompt = (
        _TABLE_PROMPT_INTRO +
        f"Database: {db_details.get('db_name')}\nTable: {table_name}\nColumns: {col_str}\n\nDescription:"
    )
    llm = await _build_llm(agent_id)
    resp = await llm.ainvoke(prompt)
    description = response_text(resp)

    # Only this table changes; every other table and all flags are re-read under a lock and
    # kept, so a description written meanwhile for another table is not lost.
    current = await table_description_db_utils.list_table_description_from_db(None, agent_id, db_id=db_id)
    rec = current.get("record") if current else None
    started = table_description_db_utils._description_map(rec.description) if rec else {}
    db_res = await table_description_db_utils.save_generated_table_descriptions(
        agent_id, db_id, started, {table_name: description},
        list(dict.fromkeys(list(started) + [table_name])),
    )
    if not (db_res and db_res.get("status")):
        raise HTTPException(status_code=500, detail="Failed to save generated table description")
    logger.info(f"[tbl-desc-one] generated for agent={agent_id} db={db_id} table={table_name}")
    return {"table_name": table_name, "description": description}
