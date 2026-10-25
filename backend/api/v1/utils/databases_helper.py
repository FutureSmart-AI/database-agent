"""
Helpers for the Multi-DB `databases` collection (docs/multi-db-spec.md §8).

Owns: list/add/get/update/delete/status/description of an agent's databases, the
primary-DB bookkeeping (§3.3), RDS discovery, and CSV/JSON bulk import.
"""
import asyncio
import csv
import io
import json
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from chatbot_management.services.logger import logger
from chatbot_management.services.sqlmodel_session import get_async_session
from models.sql_models import ChatbotConnection, ChatbotDetails
from sqlmodel import select

from agent.db_utils.database_db_utils import generate_db_id
from database_connection.db_utils.database_db_utils import test_db_connection
from database_connection.utils.common_utils import validate_database_request
from database_connection.utils.exceptions import DatabaseConnectionError
from api.v1.schemas.databases import _DEFAULT_PORT_BY_ENGINE


async def verify_agent_exists(agent_id: str) -> ChatbotDetails:
    async for session in get_async_session():
        res = await session.execute(select(ChatbotDetails).where(ChatbotDetails.agent_id == agent_id))
        agent = res.scalar_one_or_none()
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
        return agent


def _public_row(c: ChatbotConnection, include_password: bool = False, job_status: Optional[str] = None) -> Dict[str, Any]:
    """Serialize a connection row for API responses. Password masked unless requested.
    `description_status` is set | generating | failed | none — drives the UI status chip.
    `job_status` is the latest auto-generate job status for this db (running/failed/done/None)."""
    desc = (c.description or "").strip()
    if desc:
        description_status = "set"
    elif job_status == "running":
        description_status = "generating"
    elif job_status == "failed":
        description_status = "failed"
    else:
        description_status = "none"
    row = {
        "db_id": c.db_id,
        "owner_id": c.owner_id,  # agent owner, surfaced so shared-agent rows are attributable
        "db_name": c.db_name,
        "db_host": c.db_host,
        "db_user": c.db_user,
        "db_port": c.db_port,
        "db_engine": c.db_engine,
        "description": c.description,
        "description_status": description_status,
        "description_source": c.description_source,
        "description_updated_at": c.description_updated_at.isoformat() + "Z" if c.description_updated_at else None,
        "is_active": bool(c.is_active),
        "status": c.status or "untested",
        "table_count": c.table_count,
    }
    row["db_password"] = c.db_password if include_password else "***"
    return row


# Ceiling for the lazy table_count backfill on the databases listing. Introspection is a
# nice-to-have there; the listing itself must stay fast.
_BACKFILL_TIMEOUT_SECONDS = 8


async def cache_table_count(db_id: str, count: int) -> None:
    """Persist the introspected table count on the connection row.

    `table_count` is a cache, so this is best-effort: a failure here must never break the
    caller that happened to have a fresh count in hand.
    """
    try:
        async for session in get_async_session():
            res = await session.execute(
                select(ChatbotConnection).where(
                    ChatbotConnection.db_id == db_id,
                    ChatbotConnection.deleted == False,  # noqa: E712
                )
            )
            conn = res.scalar_one_or_none()
            if conn is not None and conn.table_count != count:
                conn.table_count = count
                await session.commit()
            return
    except Exception as e:
        logger.warning(f"[cache_table_count] could not store table_count for {db_id}: {e}")


async def _count_tables_live(conn: ChatbotConnection) -> Optional[int]:
    """Introspect one connection for its table count. None when the DB is unreachable."""
    try:
        from agent.db_utils import table_description_db_utils as _agent_tdu
        db_details = {
            "db_id": conn.db_id, "db_host": conn.db_host, "db_name": conn.db_name,
            "db_user": conn.db_user, "db_password": conn.db_password,
            "db_port": conn.db_port, "db_engine": conn.db_engine,
        }
        # Blocking driver call (psycopg2/pymysql) → keep it off the event loop.
        tables = await asyncio.to_thread(
            _agent_tdu.get_table_names_from_db, {"db_details": db_details}
        )
        return len(tables or [])
    except Exception as e:
        logger.warning(f"[_count_tables_live] introspection failed for {conn.db_id}: {e}")
        return None


async def _backfill_table_counts(conns: List[ChatbotConnection]) -> Dict[str, int]:
    """Fill in table_count for rows that have never been introspected.

    The column is only ever written from a live introspection, so rows created before this
    existed read as NULL and the UI renders "0 tables". Counting here is a one-time cost per
    database: the result is cached on the row and later listings read it straight back.
    Unreachable databases stay NULL and are retried on the next listing.
    """
    # Skip databases already known to be unreachable — introspecting those only buys a
    # connect timeout, and their count would be NULL either way.
    pending = [c for c in conns if c.table_count is None and (c.status or "untested") != "error"]
    if not pending:
        return {}
    try:
        # Hard ceiling on the whole backfill: the listing is the databases page's first paint,
        # so a slow or hanging database must cost the count, never the page.
        counts = await asyncio.wait_for(
            asyncio.gather(*(_count_tables_live(c) for c in pending)),
            timeout=_BACKFILL_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning(
            f"[_backfill_table_counts] timed out after {_BACKFILL_TIMEOUT_SECONDS}s "
            f"for {len(pending)} database(s); counts stay NULL and retry next listing"
        )
        return {}
    out: Dict[str, int] = {}
    for conn, count in zip(pending, counts):
        if count is not None:
            out[conn.db_id] = count
            await cache_table_count(conn.db_id, count)
    return out


async def _latest_job_status_by_db(agent_id: str) -> Dict[str, str]:
    """{db_id: latest auto-generate-description job status} (running | failed | done)."""
    from models.sql_models import DescriptionGenerationJobs
    out: Dict[str, str] = {}
    async for session in get_async_session():
        res = await session.execute(
            select(DescriptionGenerationJobs.db_id, DescriptionGenerationJobs.status)
            .where(DescriptionGenerationJobs.agent_id == agent_id)
            # Exclude table-description jobs (job_id prefixed "TBLDESC_") — this drives the
            # DB-level routing-description status chip only.
            .where(DescriptionGenerationJobs.job_id.notlike("TBLDESC%"))
            .order_by(DescriptionGenerationJobs.created_at)  # ascending → newest overwrites
        )
        for db_id, status in res.all():
            out[db_id] = status
        return out
    return out


def included_table_count(entry_flags: Any) -> Optional[int]:
    """How many tables the agent may read in one database, from its visibility flags.

    None when there is no valid flag map: the agent then reads no table at all (table access
    fails closed, agent/utils/table_access.py), but "unknown" must not be shown as a count.
    """
    from agent.utils.table_flag_writes import canonical_table_flags_for_write
    try:
        flags = canonical_table_flags_for_write(entry_flags)
    except (TypeError, ValueError):
        return None
    if not flags:
        return None
    return sum(1 for on in flags.values() if on)


async def _included_table_counts(agent_id: str) -> Dict[str, Optional[int]]:
    """{db_id: tables the agent may read}. Before this the listing carried no such figure and
    the dashboard header added up zeros: "1 database · 0 tables" on an agent reading seven."""
    from models.sql_models import TableDescription
    out: Dict[str, Optional[int]] = {}
    async for session in get_async_session():
        res = await session.execute(
            select(TableDescription.db_id, TableDescription.entry_flags)
            .where(TableDescription.agent_id == agent_id)
        )
        for db_id, flags in res.all():
            if db_id:
                out[db_id] = included_table_count(flags)
        return out
    return out


async def list_agent_databases(agent_id: str) -> List[Dict[str, Any]]:
    await verify_agent_exists(agent_id)
    jobs = await _latest_job_status_by_db(agent_id)
    included = await _included_table_counts(agent_id)
    out: List[Dict[str, Any]] = []
    async for session in get_async_session():
        res = await session.execute(
            select(ChatbotConnection)
            .where(
                (ChatbotConnection.agent_id == agent_id) | (ChatbotConnection.chatbot_id == agent_id),
                ChatbotConnection.deleted == False,  # noqa: E712 — tombstones stay hidden
            )
            .order_by(ChatbotConnection.is_active.desc(), ChatbotConnection.created_at)
        )
        conns = list(res.scalars().all())
        fresh_counts = await _backfill_table_counts(conns)
        for c in conns:
            row = _public_row(c, job_status=jobs.get(c.db_id))
            if row["table_count"] is None and c.db_id in fresh_counts:
                row["table_count"] = fresh_counts[c.db_id]
            row["included_table_count"] = included.get(c.db_id)
            out.append(row)
    return out


async def _get_row(session, agent_id: str, db_id: str) -> ChatbotConnection:
    res = await session.execute(
        select(ChatbotConnection).where(
            ChatbotConnection.db_id == db_id,
            (ChatbotConnection.agent_id == agent_id) | (ChatbotConnection.chatbot_id == agent_id),
            ChatbotConnection.deleted == False,  # noqa: E712 — a deleted DB reads as 404
        )
    )
    conn = res.scalar_one_or_none()
    if not conn:
        raise HTTPException(status_code=404, detail=f"Database {db_id} not found for agent {agent_id}")
    return conn


async def get_agent_database(agent_id: str, db_id: str) -> Dict[str, Any]:
    await verify_agent_exists(agent_id)
    jobs = await _latest_job_status_by_db(agent_id)
    async for session in get_async_session():
        conn = await _get_row(session, agent_id, db_id)
        return _public_row(conn, job_status=jobs.get(db_id))


async def _test_or_400(body_like: Any) -> None:
    """Validate + test a connection; raise HTTPException(400) on failure."""
    is_valid, error_msg = validate_database_request(
        engine=body_like["db_engine"], host=body_like["db_host"],
        db_name=body_like["db_name"], port=body_like["db_port"],
    )
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)
    try:
        result = await test_db_connection(
            host=body_like["db_host"], user=body_like["db_user"], password=body_like["db_password"],
            db=body_like["db_name"], port=body_like["db_port"], db_engine=body_like["db_engine"],
        )
        if not result.get("status"):
            raise HTTPException(status_code=400, detail=result.get("message", "Connection test failed"))
    except DatabaseConnectionError as e:
        raise HTTPException(status_code=400, detail=str(e))


async def test_connection(body: Any) -> Dict[str, Any]:
    """Validate + test a connection without saving it. 400 on failure."""
    await _test_or_400({
        "db_host": body.db_host, "db_name": body.db_name, "db_user": body.db_user,
        "db_password": body.db_password, "db_port": body.db_port, "db_engine": body.db_engine,
    })
    return {"status": "connected", "message": "Connection successful"}


async def add_agent_database(agent_id: str, body: Any) -> Dict[str, Any]:
    """Add a DB to an agent. Description is OPTIONAL: when blank, the DB is saved INACTIVE and
    an auto-generate-description job is kicked off in the background (status = 'generating')."""
    agent = await verify_agent_exists(agent_id)

    # Reject duplicates: same connection identity (host + name + port + engine) already attached
    # to this agent. Identity mirrors update_agent_database's change-detection tuple; db_user is
    # intentionally excluded — a different login to the same database is still the same database.
    # Enforced here (not just the UI) so direct API calls and bulk import are covered too.
    norm_engine = (body.db_engine or "mysql").lower()
    async for session in get_async_session():
        res = await session.execute(
            select(ChatbotConnection).where(
                (ChatbotConnection.agent_id == agent_id) | (ChatbotConnection.chatbot_id == agent_id),
                ChatbotConnection.db_host == body.db_host,
                ChatbotConnection.db_name == body.db_name,
                ChatbotConnection.db_port == body.db_port,
                # Tombstones must not block re-adding a database that was deleted earlier.
                ChatbotConnection.deleted == False,  # noqa: E712
            )
        )
        if any((c.db_engine or "").lower() == norm_engine for c in res.scalars().all()):
            raise HTTPException(status_code=409, detail="This database is already connected.")

    payload = {
        "db_host": body.db_host, "db_name": body.db_name, "db_user": body.db_user,
        "db_password": body.db_password, "db_port": body.db_port, "db_engine": body.db_engine,
    }
    await _test_or_400(payload)

    description = (getattr(body, "description", None) or "").strip()
    db_id = generate_db_id()
    async for session in get_async_session():
        conn = ChatbotConnection(
            db_id=db_id, user_id=(agent.owner_id or agent.user_id or "unknown"),
            owner_id=agent.owner_id,  # explicit owner, distinct from the creator in user_id
            chatbot_id=agent_id, agent_id=agent_id,
            db_host=body.db_host, db_name=body.db_name, db_user=body.db_user,
            db_password=body.db_password, db_port=body.db_port,
            db_engine=(body.db_engine or "mysql").lower(),  # normalize: store lowercase
            description=(description or None),
            description_source=("manual" if description else None),
            description_updated_at=(datetime.utcnow() if description else None),
            is_active=bool(description),  # inactive until a description exists (skipped by router)
            status="connected",
            created_at=datetime.utcnow(), updated_at=datetime.utcnow(),
        )
        session.add(conn)
        await session.commit()

    description_status = "set"
    if not description:
        # Auto-generate in the background; UI polls and shows "Generating description…".
        try:
            from api.v1.utils.description_jobs_helper import start_description_job
            await start_description_job(agent_id, db_id, apply_to_db=True)
            description_status = "generating"
        except Exception as e:
            logger.warning(f"[add_db] auto-generate kickoff failed for {db_id}: {e}")
            description_status = "none"

    # Table descriptions are always blank for a new DB, so fill them in the background too.
    # overwrite=False: anything saved manually before the job finishes is kept.
    try:
        from api.v1.utils.description_jobs_helper import start_table_description_job
        await start_table_description_job(agent_id, db_id, overwrite=False)
    except Exception as e:
        logger.warning(f"[add_db] table-description kickoff failed for {db_id}: {e}")

    label = f"'{body.db_name}'" if getattr(body, "db_name", None) else "Database"
    if description_status == "generating":
        message = f"Database {label} added. Generating description…"
    elif description_status == "none":
        message = f"Database {label} added, but description generation could not be started."
    else:
        message = f"Database {label} added successfully."

    return {"db_id": db_id, "status": "connected", "description_status": description_status, "message": message}


async def update_agent_database(agent_id: str, db_id: str, body: Any, user_id: Optional[str] = None) -> Dict[str, Any]:
    """Partial update. Re-tests + flags db_changed when connection identity changes.

    user_id: acting dashboard user, recorded as updated_by; NULL for internal / API-key
    (master) callers. user_id on the row is the fixed creator and is never overwritten.
    """
    await verify_agent_exists(agent_id)
    fields = {k: v for k, v in body.model_dump().items() if v is not None}

    async for session in get_async_session():
        conn = await _get_row(session, agent_id, db_id)
        prev = (conn.db_host, conn.db_name, conn.db_port, conn.db_engine)

        merged = {
            "db_host": fields.get("db_host", conn.db_host),
            "db_name": fields.get("db_name", conn.db_name),
            "db_user": fields.get("db_user", conn.db_user),
            "db_password": fields.get("db_password", conn.db_password),
            "db_port": fields.get("db_port", conn.db_port),
            "db_engine": (fields.get("db_engine", conn.db_engine) or "mysql").lower(),  # normalize
        }
        identity_changed = (prev != (merged["db_host"], merged["db_name"], merged["db_port"], merged["db_engine"]))
        if identity_changed:
            await _test_or_400(merged)

        for k, v in merged.items():
            setattr(conn, k, v)
        if "description" in fields:
            new_desc = (fields["description"] or "").strip()
            had_desc = bool((conn.description or "").strip())
            conn.description = new_desc or None
            if new_desc:
                conn.description_source = "manual"
                conn.description_updated_at = datetime.utcnow()
            # First time a description is set, the DB becomes eligible (active) for routing.
            if new_desc and not had_desc:
                conn.is_active = True
        if identity_changed:
            conn.status = "connected"
        conn.updated_at = datetime.utcnow()
        if user_id:
            conn.updated_by = user_id  # acting dashboard user on this edit
        session.add(conn)
        await session.commit()

    return {"message": "Database updated", "db_changed": identity_changed, "db_id": db_id, "agent_id": agent_id}


async def delete_agent_database(agent_id: str, db_id: str, user_id: Optional[str] = None) -> None:
    """Delete a DB + all its scoped metadata. No primary bookkeeping needed —
    the primary is implicitly the oldest remaining active DB.

    Soft delete: the row is retained as a tombstone (deleted/deleted_at/deleted_by) so the
    deletion is auditable — a hard delete left nothing to record who detached the database.
    The stored password is cleared, since retaining a live credential for a detached database
    is a liability the audit trail does not need. Readers filter on `deleted`, so the DB
    disappears from listings, routing and query execution exactly as before.

    user_id: acting dashboard user; NULL for internal / API-key (master) callers.
    """
    await verify_agent_exists(agent_id)
    async for session in get_async_session():
        conn = await _get_row(session, agent_id, db_id)
        conn.deleted = True
        conn.deleted_at = datetime.utcnow()
        if user_id:
            conn.deleted_by = user_id
        conn.is_active = False  # keep it out of any is_active-only read path too
        conn.db_password = ""   # do not retain credentials for a detached database
        session.add(conn)
        await session.commit()

    # Cascade per-DB metadata cleanup (best-effort; non-blocking on failure).
    try:
        from api.v1.utils.multi_db_metadata import purge_database_metadata
        await purge_database_metadata(agent_id, db_id)
    except Exception as e:
        logger.warning(f"[delete_db] metadata purge failed for {db_id}: {e}")


async def bulk_delete_databases(agent_id: str, db_ids: List[str], user_id: Optional[str] = None) -> Dict[str, Any]:
    """Delete multiple databases (and their scoped metadata) in one action.
    Best-effort per DB: one failure does not abort the others. Returns per-DB results plus a
    count-aware summary message."""
    await verify_agent_exists(agent_id)

    results: List[Dict[str, Any]] = []
    deleted = failed = 0
    for db_id in db_ids:
        try:
            await delete_agent_database(agent_id, db_id, user_id=user_id)
            results.append({"db_id": db_id, "status": "deleted"})
            deleted += 1
        except HTTPException as e:
            results.append({"db_id": db_id, "status": "failed", "error": str(e.detail)})
            failed += 1
        except Exception as e:
            results.append({"db_id": db_id, "status": "failed", "error": str(e)})
            failed += 1

    db_noun = "database" if deleted == 1 else "databases"
    if failed == 0:
        message = f"{deleted} {db_noun} deleted successfully."
    else:
        fail_noun = "database" if failed == 1 else "databases"
        if deleted == 0:
            message = f"No databases deleted - {failed} {fail_noun} failed."
        else:
            message = f"{deleted} {db_noun} deleted successfully; {failed} {fail_noun} failed."

    return {"results": results, "deleted": deleted, "failed": failed, "message": message}


async def set_database_status(agent_id: str, db_id: str, is_active: bool, user_id: Optional[str] = None) -> Dict[str, Any]:
    await verify_agent_exists(agent_id)
    async for session in get_async_session():
        conn = await _get_row(session, agent_id, db_id)
        conn.is_active = is_active
        conn.updated_at = datetime.utcnow()
        if user_id:
            conn.updated_by = user_id  # acting dashboard user on this edit
        session.add(conn)
        await session.commit()
    return {"db_id": db_id, "is_active": is_active}


async def set_database_description(agent_id: str, db_id: str, description: str, user_id: Optional[str] = None) -> Dict[str, Any]:
    # Explicitly setting a description requires content (the PATCH /description endpoint).
    if not description or not description.strip():
        raise HTTPException(status_code=400, detail="description is required")
    await verify_agent_exists(agent_id)
    async for session in get_async_session():
        conn = await _get_row(session, agent_id, db_id)
        had_desc = bool((conn.description or "").strip())
        conn.description = description.strip()
        conn.description_source = "manual"
        conn.description_updated_at = datetime.utcnow()
        if not had_desc:
            conn.is_active = True  # description set → eligible for routing
        conn.updated_at = datetime.utcnow()
        if user_id:
            conn.updated_by = user_id  # acting dashboard user on this edit
        session.add(conn)
        await session.commit()
    return {"message": "Description updated", "db_id": db_id}


async def check_all_databases(agent_id: str) -> Dict[str, Any]:
    """Health-check every database: test the connection (status + response time) and report
    description status. Persists the connection result to each row's `status`."""
    import time
    await verify_agent_exists(agent_id)
    jobs = await _latest_job_status_by_db(agent_id)
    conns: List[ChatbotConnection] = []
    async for session in get_async_session():
        res = await session.execute(
            select(ChatbotConnection)
            .where(
                (ChatbotConnection.agent_id == agent_id) | (ChatbotConnection.chatbot_id == agent_id),
                ChatbotConnection.deleted == False,  # noqa: E712 — never health-check a detached DB
            )
            .order_by(ChatbotConnection.is_active.desc(), ChatbotConnection.created_at)
        )
        conns = res.scalars().all()

    async def _check(c: ChatbotConnection) -> Dict[str, Any]:
        t = time.perf_counter()
        conn_status, err = "failed", None
        try:
            r = await test_db_connection(host=c.db_host, user=c.db_user, password=c.db_password,
                                         db=c.db_name, port=c.db_port, db_engine=c.db_engine)
            if r.get("status"):
                conn_status = "connected"
            else:
                err = r.get("message")
        except Exception as e:
            err = str(e)
        desc = (c.description or "").strip()
        js = jobs.get(c.db_id)
        dstat = "set" if desc else ("generating" if js == "running" else ("failed" if js == "failed" else "none"))
        return {
            "db_id": c.db_id, "db_name": c.db_name,
            "connection": conn_status, "response_ms": int((time.perf_counter() - t) * 1000),
            "error": err, "description_status": dstat,
            "description_source": c.description_source,
            "description_updated_at": c.description_updated_at.isoformat() + "Z" if c.description_updated_at else None,
            "is_active": bool(c.is_active),
        }

    results = list(await asyncio.gather(*[_check(c) for c in conns])) if conns else []

    # Persist the latest connection result to each row's status.
    async for session in get_async_session():
        for r in results:
            row = (await session.execute(
                select(ChatbotConnection).where(
                    ChatbotConnection.db_id == r["db_id"],
                    ChatbotConnection.deleted == False,  # noqa: E712
                )
            )).scalar_one_or_none()
            if row:
                row.status = "connected" if r["connection"] == "connected" else "error"
                row.updated_at = datetime.utcnow()
                session.add(row)
        await session.commit()

    return {"checked_at": datetime.utcnow().isoformat() + "Z", "databases": results}


# ── RDS discovery ──────────────────────────────────────────────────────────────

# The user waits on this call, so every connect must fail fast rather than hang.
_RDS_CONNECT_TIMEOUT_SECONDS = 5
# A host that accepts the connection can still stall on the query, which the connect timeout
# does not cover. Bound the statement too.
_RDS_STATEMENT_TIMEOUT_MS = 5000


def _rds_list_sync(host: str, user: str, password: str, port: int, engine: str) -> List[Dict[str, Any]]:
    """List the databases on an instance, over exactly ONE connection. Runs in a thread.

    Step 1 of the RDS flow needs names: they are what the user picks from. Table counts are
    decoration here, and in Postgres they are expensive decoration - its catalog is
    per-database, so counting means a fresh connection per database. Doing that inline made
    discovery scale with the size of the instance and time out on hosts that had simply grown
    (the CDN closes the origin connection long before 20-odd sequential logins finish).

    So counts are only reported when they are free. MySQL keeps an instance-wide
    information_schema, so one extra query on the connection already open answers for every
    database. Postgres reports None, and the count is filled in later by the table_count
    backfill on the databases listing, where it is already cached per row and costs the user
    nothing to wait for.
    """
    import pymysql
    import psycopg2

    engine = (engine or "mysql").lower()
    if engine == "mysql":
        con = pymysql.connect(host=host, user=user, passwd=password, port=int(port),
                              connect_timeout=_RDS_CONNECT_TIMEOUT_SECONDS,
                              read_timeout=_RDS_STATEMENT_TIMEOUT_MS / 1000)
        try:
            with con.cursor() as cur:
                cur.execute(
                    "SELECT table_schema, COUNT(*) FROM information_schema.tables GROUP BY table_schema"
                )
                counts = {r[0]: int(r[1]) for r in cur.fetchall()}
                cur.execute("SHOW DATABASES")
                return [
                    {"db_name": r[0], "table_count": counts.get(r[0], 0)}
                    for r in cur.fetchall()
                    if r[0] not in ("information_schema", "performance_schema", "mysql", "sys")
                ]
        finally:
            con.close()
    if engine == "postgresql":
        con = psycopg2.connect(host=host, user=user, password=password, port=int(port),
                               dbname="postgres", connect_timeout=_RDS_CONNECT_TIMEOUT_SECONDS,
                               options="-c statement_timeout=%d" % _RDS_STATEMENT_TIMEOUT_MS)
        try:
            con.autocommit = True
            with con.cursor() as cur:
                cur.execute("SELECT datname FROM pg_database WHERE datistemplate=false AND datname<>'postgres'")
                return [{"db_name": r[0], "table_count": None} for r in cur.fetchall()]
        finally:
            con.close()
    raise HTTPException(status_code=400, detail=f"Unsupported engine: {engine}")


async def list_rds_databases(body: Any) -> Dict[str, Any]:
    try:
        databases = await asyncio.to_thread(
            _rds_list_sync, body.db_host, body.db_user, body.db_password, body.db_port, body.db_engine
        )
        return {"databases": databases}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"RDS list failed: {e}")
        # The driver's own wording for an unreachable host ("timeout expired") says nothing about
        # what to do next, and a host that is up but not open to this service is the usual reason
        # a first-time connection fails. Say so.
        detail = str(e).strip()
        if any(t in detail.lower() for t in ("timeout", "refused", "could not connect", "can't connect")):
            detail = (f"{detail} (no answer within {_RDS_CONNECT_TIMEOUT_SECONDS}s). Check the host "
                      f"and port, and that the instance accepts connections from this service.")
        raise HTTPException(status_code=400, detail=f"Could not list databases on instance: {detail}")


# ── Bulk import ──────────────────────────────────────────────────────────────

def _parse_bulk_file(raw: bytes, filename: str) -> List[Dict[str, Any]]:
    name = (filename or "").lower()
    text = raw.decode("utf-8-sig", errors="replace")
    if name.endswith(".json") or text.lstrip().startswith(("[", "{")):
        data = json.loads(text)
        rows = data if isinstance(data, list) else data.get("databases", [])
        return [dict(r) for r in rows]
    # CSV
    reader = csv.DictReader(io.StringIO(text))
    return [dict(r) for r in reader]


async def bulk_import_databases(agent_id: str, raw: bytes, filename: str) -> Dict[str, Any]:
    await verify_agent_exists(agent_id)
    try:
        rows = _parse_bulk_file(raw, filename)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not parse file: {e}")

    def _g(row, *keys):  # first non-empty value among aliases
        for k in keys:
            v = row.get(k)
            if v not in (None, ""):
                return v
        return None

    results: List[Dict[str, Any]] = []
    added = failed = 0
    for idx, row in enumerate(rows, start=1):
        # Accept both db_* names and the UI template's short names (engine/host/port/...).
        db_name = _g(row, "db_name", "database") or ""
        # Description is OPTIONAL — blank rows are added inactive + auto-generated.
        description = (_g(row, "description") or "").strip()
        try:
            class _B:  # lightweight adapter matching AddDatabaseRequest attrs
                pass
            b = _B()
            b.db_host = _g(row, "db_host", "host"); b.db_name = db_name
            b.db_user = _g(row, "db_user", "user"); b.db_password = _g(row, "db_password", "password")
            b.db_engine = (_g(row, "db_engine", "engine") or "mysql")
            # A row may omit the port; fall back to the engine's own default rather than MySQL's,
            # which a PostgreSQL row could only fail on.
            _port = _g(row, "db_port", "port")
            b.db_port = int(_port) if _port else _DEFAULT_PORT_BY_ENGINE.get(b.db_engine.lower(), 3306)
            b.description = description

            res = await add_agent_database(agent_id, b)
            label = f"'{db_name}'" if db_name else f"row {idx}"
            results.append({"row": idx, "db_name": db_name, "status": "added",
                            "db_id": res["db_id"], "description_status": res.get("description_status"),
                            "message": f"Database {label} imported successfully."})
            added += 1
        except HTTPException as e:
            label = f"'{db_name}'" if db_name else f"row {idx}"
            results.append({"row": idx, "db_name": db_name, "status": "failed", "error": str(e.detail),
                            "message": f"Database {label} failed to import: {e.detail}"})
            failed += 1
        except Exception as e:
            label = f"'{db_name}'" if db_name else f"row {idx}"
            results.append({"row": idx, "db_name": db_name, "status": "failed", "error": str(e),
                            "message": f"Database {label} failed to import: {e}"})
            failed += 1

    # Human-readable summary with correct singular/plural (shown by the UI).
    if added == 0 and failed == 0:
        message = "No databases found to import."
    else:
        db_noun = "database" if added == 1 else "databases"
        if failed == 0:
            message = f"{added} {db_noun} imported successfully."
        else:
            row_noun = "row" if failed == 1 else "rows"
            if added == 0:
                message = f"No databases imported - {failed} {row_noun} failed."
            else:
                message = f"{added} {db_noun} imported successfully; {failed} {row_noun} failed."

    return {"results": results, "added": added, "failed": failed, "message": message}
