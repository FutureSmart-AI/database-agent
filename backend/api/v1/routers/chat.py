"""
RESTful API endpoints for Chat Management
Following REST best practices for managing agent chat interactions
"""
from fastapi import HTTPException, Depends, APIRouter, Path, Query, BackgroundTasks
from agent.utils.model_profiles import ModelConfigurationError
from starlette.requests import Request
from chatbot_management.utils.api_validation import get_api_key_or_session
from chatbot_management.services.logger import logger
import traceback
from typing import Optional
from fastapi.responses import StreamingResponse, JSONResponse
import uuid
import time
import json
from agent.utils.authorization import require_agent_permission

# Import from agent module
from agent.db_utils.common_db_utils import (
    check_direct_chatbot_access,
    get_owner_user_id_by_chatbot_id,
)
from agent.db_utils.session_db_utils import (
    log_new_session as agent_log_new_session,
    get_session_chat_counter_from_db
)
from agent.runner import run_agent_flow
from api.v1.utils.chat_helper import (
    get_past_messages_safe, get_owner_email_by_agent_id, ensure_session_belongs_to_agent,
    get_agent_with_visibility, get_agent_runtime_db,
    get_chat_log_for_export, get_session_messages_data,
    build_chat_response, maybe_upload_csv_export, persist_chat_logs,
    apply_agent_answer_settings, persist_health_event
)

# Import schemas from centralized location
from api.v1.schemas.chat import (
    ChatRequest,
    SessionMessageRequest,
    MessageHistoryResponse,
)
from otel_tracing import track_time
import asyncio

router = APIRouter(prefix="/v1")


def _build_follow_up_context(result: dict) -> Optional[str]:
    """Ground follow-up generation in what was actually queried and returned.

    Without this, the follow-up model only sees the conversation text (answer truncated to
    800 chars) and tends to produce generic questions. The SQL + result columns + a row sample
    tell it exactly which entities/metrics exist to ask about. Returns None when the turn
    produced no SQL/data (router END path) — the history-only prompt applies then.
    """
    sql = (result.get("sql_query") or "").strip()
    cols = result.get("db_columns") or []
    rows = result.get("db_result") or []
    if not sql and not rows:
        return None
    # Only supply data context when the follow-up model would otherwise be missing information:
    # the current answer is passed to follow-up generation up to 2500 chars (follow_up.py), so
    # answers under that already carry everything. For those, extra SQL/row context mostly leaks
    # internals into the generated questions (measured in A/B) — skip it.
    if len(result.get("response") or "") <= 2500:
        return None
    parts = []
    if sql:
        parts.append(f"### Executed SQL\n```sql\n{sql[:800]}\n```")
    if rows and cols:
        # Markdown table: pairs every value with its column name — far more readable (for both
        # the model and anyone inspecting the prompt in LangSmith) than a JSON array-of-arrays.
        try:
            from agent.utils.common_utils import serialize_db_value

            def _cell(v) -> str:
                v = serialize_db_value(v)
                s = "" if v is None else str(v)
                s = s.replace("|", "\\|").replace("\n", " ")
                return s if len(s) <= 40 else s[:37] + "..."

            names = [str(c) for c in cols]
            lines = [
                "| " + " | ".join(names) + " |",
                "|" + "---|" * len(names),
            ]
            for r in rows[:8]:
                vals = list(r) if isinstance(r, (list, tuple)) else [r]
                vals += [""] * (len(names) - len(vals))
                lines.append("| " + " | ".join(_cell(v) for v in vals[: len(names)]) + " |")
            table = "\n".join(lines)[:1200]
            parts.append(f"### Result sample ({min(len(rows), 8)} of {len(rows)} rows)\n{table}")
        except Exception:
            pass
    elif cols:
        parts.append("### Result columns\n" + ", ".join(str(c) for c in cols))
    return "\n\n".join(parts) if parts else None


async def _generate_follow_up_safe(body, owner_email, agent_id, past_messages, result):
    """Generate follow-up questions AFTER the answer is ready, off the agent's critical path.

    Runs concurrently with export/persist (non-stream) or after the answer chunks have been
    yielded (stream), so the user never waits on it. Returns None when not requested; never
    raises (generate_follow_up_questions itself returns [] on failure).
    """
    # Parent trace headers captured inside run_agent_flow's traceable scope — attach the
    # follow-up run to the SAME LangSmith trace (nested under it) even though it executes
    # after that scope closed. Pop regardless of the flag so the key never lingers in result.
    parent_headers = result.pop("_ls_parent_headers", None)
    if not getattr(body, "follow_up", False):
        return None
    try:
        from agent.utils.follow_up import generate_follow_up_questions
        kwargs = dict(
            owner_id=owner_email,
            agent_id=agent_id,
            messages=past_messages,
            refined_query=result.get("refined_query") or body.query,
            response=result.get("response", ""),
            follow_up_context=_build_follow_up_context(result),
        )
        if parent_headers:
            try:
                from langsmith.run_helpers import tracing_context
                with tracing_context(parent=parent_headers):
                    return await generate_follow_up_questions(**kwargs)
            except ImportError:
                pass
        return await generate_follow_up_questions(**kwargs)
    except Exception as e:
        logger.error(f"Follow-up generation failed (non-blocking): {e}")
        return None


async def enforce_query_cap(owner_id: Optional[str], *, surface: str) -> None:
    """Refuse with 429 when this owner has used their rolling-24h allowance.

    Shared by both chat surfaces so the limit, the window and the wording cannot drift
    apart. Call AFTER the owner is known and BEFORE any model call, so a refused question
    costs nothing.

    Does nothing when `owner_id` is falsy — there is nobody to charge, and refusing an
    unattributed request would block traffic no cap can meter.

    FAILS OPEN by way of `check_query_allowed`: a cap that cannot be read allows the
    question and logs an error, because refusing a paying customer over a database hiccup
    is worse than letting a few extra questions through.
    """
    if not owner_id:
        return

    from chatbot_management.db_utils.owner_config_db_utils import check_query_allowed
    from chatbot_management.services.sqlmodel_session import async_session

    async with async_session() as session:
        breach = await check_query_allowed(session, owner_id)
    if not breach:
        return

    logger.warning(
        f"Chat refused, query cap reached | surface={surface} owner_id={owner_id} "
        f"used={breach['used']} cap={breach['cap']} resets_at={breach['resets_at']}"
    )
    when = (breach["resets_at"] or "").replace("T", " ")[:16]
    # 429, not 403: the request is well-formed and the caller is authorised — they have
    # used their allowance. A 403 would suggest they may not use the agent at all.
    raise HTTPException(
        status_code=429,
        detail=(
            f"Query limit reached: {breach['used']} of {breach['cap']} in the last 24 "
            f"hours. " + (f"You can ask again after {when} UTC. " if when else "")
            + "Ask an administrator to raise the limit if you need more."
        ),
    )


@router.post("/agents/{agent_id}/chat")
@track_time("API: NL2SQL - Chat")
async def chat_with_agent(
    agent_id: str = Path(..., description="Agent ID"),
    stream: bool = Query(False, description="Enable streaming response"),
    body: ChatRequest = None,
    request: Request = None,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("use")),
):
    """
    Send a chat message to an agent

    """
    request_id = str(uuid.uuid4())  # Unique ID for tracking this request
    # Session (browser) users: identity is fixed by their token — never trust caller-supplied user_id.
    # Trusted master-key callers (e.g. the chat service) declare the end user via body.user_id.
    auth_type = auth.get("auth_type")
    if auth_type == "session":
        user_id = auth.get("user_id")
    else:
        user_id = getattr(body, "user_id", None) or auth.get("user_id")
    logger.info(f"[CONCURRENCY] REQUEST START: request_id={request_id} agent_id={agent_id} timestamp={time.time()} user={user_id} auth_type={auth.get('auth_type')} stream={stream}")
    try:
        agent, show_sql_query, show_db_result, include_debug_block = await get_agent_with_visibility(agent_id)
        logger.info(f"Agent visibility flags | show_sql_query={show_sql_query} show_db_result={show_db_result}")

        # Any answer flag the caller left out falls back to what the dashboard saved on the agent.
        effective_settings = apply_agent_answer_settings(agent, body)
        logger.info(f"Effective answer settings | {effective_settings}")

        owner_email = await get_owner_email_by_agent_id(agent_id)

        # The owner's rolling-24h query cap. Checked here — after the owner is known,
        # before any model call — so a refused question costs nothing, and it covers
        # streaming and non-streaming alike since both paths run below this point. It also
        # covers the session-message route, which delegates to this function.
        await enforce_query_cap(owner_email, surface="agent_chat")

        chat_id = str(uuid.uuid4())
        session_id = body.session_id
        await ensure_session_belongs_to_agent(session_id, agent_id)

        message_history = await get_past_messages_safe(session_id, user_id, agent_id, body.query)
        past_messages = message_history["past_messages"]
        session_id = message_history["session_id"]

        runtime_db, db_fetch_elapsed = await get_agent_runtime_db(agent_id)

        if stream:
            logger.info(f"[CONCURRENCY] Streaming response setup: request_id={request_id} agent_id={agent_id} session_id={session_id}")
            session_chat_counter = await get_session_chat_counter_from_db(session_id) or 0

            async def agent_stream():
                try:
                    agent_start_time = time.time()
                    # follow_up=False here: follow-up questions are generated AFTER the answer
                    # chunks are yielded (concurrently with export/persist) so they never delay
                    # the user's first chunk.
                    result = await run_agent_flow(
                        query=body.query, past_messages=past_messages, table_descriptions=None,
                        runtime_db_details=runtime_db, selected_tables=None, few_shot_examples=None,
                        user_id=user_id, owner_id=owner_email, agent_id=agent_id,
                        allowed_graphs=body.allowed_charts, include_graph_output=bool(body.chart_output),
                        session_id=session_id, request_id=request_id, follow_up=False,
                        chat_id=chat_id,
                    )
                    agent_elapsed = time.time() - agent_start_time
                    final_text = result.get("response", "")

                    for sentence in filter(None, [s.strip() for s in final_text.split('.')]):
                        yield f"data: {json.dumps({'chunk': sentence + '.', 'session_id': session_id})}\n\n"

                    follow_up_qs, export_url, _, _ = await asyncio.gather(
                        _generate_follow_up_safe(body, owner_email, agent_id, past_messages, result),
                        maybe_upload_csv_export(result, agent_id, session_id, chat_id),
                        persist_chat_logs(session_id, user_id, agent_id, chat_id, body, result, agent_elapsed, db_fetch_elapsed, include_debug_block),
                        persist_health_event(session_id, user_id, agent_id, chat_id, request_id,
                                             result, agent_elapsed, db_fetch_elapsed,
                                             owner_email, auth_type),
                    )
                    result["follow_up_questions"] = follow_up_qs
                    final_response = build_chat_response(result, body, session_id, chat_id, show_sql_query, show_db_result, export_url)

                    from agent.utils.common_utils import serialize_db_value
                    yield f"full_metadata: {json.dumps(serialize_db_value(final_response))}\n\n"
                except Exception as e:
                    logger.error(f"[STREAMING ERROR] {str(e)}")
                    # Record the failure too — a health store that only sees successes
                    # reports a 100% success rate no matter how badly the agent is doing.
                    await persist_health_event(
                        session_id, user_id, agent_id, chat_id, request_id,
                        locals().get("result") or {}, time.time() - agent_start_time,
                        db_fetch_elapsed, owner_email, auth_type, error=e,
                    )
                    yield f"full_metadata: {json.dumps({'error': str(e)})}\n\n"

            logger.info(f"[CONCURRENCY] STREAM EXIT: request_id={request_id} agent_id={agent_id} session_id={session_id} timestamp={time.time()}")
            return StreamingResponse(agent_stream(), media_type="text/event-stream")
        else:
            agent_start_time = time.time()
            # follow_up=False here: follow-up generation runs concurrently with the S3 export and
            # log persistence below instead of serially inside the agent flow.
            result = await run_agent_flow(
                query=body.query, past_messages=past_messages, table_descriptions=None,
                runtime_db_details=runtime_db, selected_tables=None, few_shot_examples=None,
                user_id=user_id, owner_id=owner_email, agent_id=agent_id,
                allowed_graphs=body.allowed_charts, include_graph_output=bool(body.chart_output),
                session_id=session_id, request_id=request_id, follow_up=False,
                chat_id=chat_id,
            )
            agent_elapsed = time.time() - agent_start_time

            follow_up_qs, export_url, _, _ = await asyncio.gather(
                _generate_follow_up_safe(body, owner_email, agent_id, past_messages, result),
                maybe_upload_csv_export(result, agent_id, session_id, chat_id),
                persist_chat_logs(session_id, user_id, agent_id, chat_id, body, result, agent_elapsed, db_fetch_elapsed, include_debug_block),
                persist_health_event(session_id, user_id, agent_id, chat_id, request_id,
                                     result, agent_elapsed, db_fetch_elapsed,
                                     owner_email, auth_type),
            )
            result["follow_up_questions"] = follow_up_qs
            final_response = build_chat_response(result, body, session_id, chat_id, show_sql_query, show_db_result, export_url)

            logger.info(f"[CONCURRENCY] NON-STREAM EXIT: request_id={request_id} agent_id={agent_id} session_id={session_id} timestamp={time.time()}")
            from agent.utils.common_utils import serialize_db_value
            return JSONResponse(serialize_db_value(final_response))

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"[CONCURRENCY] REQUEST ERROR: request_id={request_id} agent_id={agent_id} error={str(exc)} timestamp={time.time()}")
        # Same reason as the streaming branch: failures must reach the health store, or
        # the failure rate is structurally unmeasurable. Best-effort — a monitoring write
        # must never replace the real exception the caller needs to see.
        try:
            await persist_health_event(
                locals().get("session_id"), user_id, agent_id,
                locals().get("chat_id") or str(uuid.uuid4()),
                request_id, locals().get("result") or {},
                time.time() - locals().get("agent_start_time", time.time()),
                locals().get("db_fetch_elapsed") or 0, locals().get("owner_email"),
                auth_type, error=exc,
            )
        except Exception:
            pass
        if isinstance(exc, ModelConfigurationError):
            raise HTTPException(status_code=400, detail={"code": "model_configuration_error",
                                                        "message": str(exc)}) from exc
        raise





@router.get("/sessions/{session_id}/export")
async def export_session_csv(
    session_id: str = Path(..., description="Session ID"),
    chat_id: Optional[str] = Query(None, description="Specific chat turn to export. Omit to get the most recent."),
    auth: dict = Depends(get_api_key_or_session),
):
    """
    Return a fresh S3 pre-signed CSV download URL.

    - chat_id provided → that exact query turn's CSV (works forever).
    - No chat_id → most recent SQL result in the session.

    UI only needs session_id + chat_id (both already in the orchestration response).
    No NL2SQL agent_id required.
    """
    from agent.utils.s3_export_utils import (
        build_export_s3_key, generate_export_presigned_url,
        check_s3_object_exists, CSV_EXPORT_URL_EXPIRY,
    )
    chat_log = await get_chat_log_for_export(session_id, chat_id)
    if not chat_log:
        detail = f"Chat turn {chat_id} not found" if chat_id else "No SQL result found for this session"
        raise HTTPException(status_code=404, detail=detail)
    if not chat_log.sql_query:
        raise HTTPException(status_code=404, detail="This chat turn has no SQL result to export")
    s3_key = build_export_s3_key(chat_log.agent_id, session_id, chat_log.chat_id)
    if not await check_s3_object_exists(s3_key):
        raise HTTPException(status_code=404, detail="Export file not available. The query may have been made before export was enabled.")
    url = await generate_export_presigned_url(s3_key)
    if not url:
        raise HTTPException(status_code=500, detail="Could not generate export URL")
    logger.info(f"[EXPORT] Fresh URL issued | session_id={session_id} | chat_id={chat_log.chat_id}")
    return JSONResponse({"export_url": url, "expires_in_seconds": CSV_EXPORT_URL_EXPIRY, "chat_id": chat_log.chat_id})


@router.post("/agents/{agent_id}/sessions/{session_id}/messages")
async def send_message_to_session(
    agent_id: str = Path(..., description="Agent ID"),
    session_id: str = Path(..., description="Session ID"),
    stream: bool = Query(False, description="Enable streaming response"),
    body: SessionMessageRequest = None,
    request: Request = None,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("use")),
):
    """
    Send a message to an existing session

    """
    try:
        # Convert SessionMessageRequest to ChatRequest and set session_id from path.
        # user_id is carried over; honored only for master-key callers.
        chat_request = ChatRequest(
            query=body.query,
            session_id=session_id,  # Set from URL path
            user_id=getattr(body, "user_id", None),
            debug_info=body.debug_info,
            chart_output=body.chart_output,
            allowed_charts=body.allowed_charts,
            follow_up=body.follow_up,
        )

        # Call the main chat endpoint with the session_id set
        return await chat_with_agent(
            agent_id=agent_id,
            stream=stream,
            body=chat_request,
            request=request,
            background_tasks=background_tasks,
            auth=auth
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending message to session: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/agents/{agent_id}/sessions/{session_id}/messages")
async def get_session_messages(
    agent_id: str = Path(..., description="Agent ID"),
    session_id: str = Path(..., description="Session ID"),
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("use")),
):
    """
    Get message history for a session
    """
    try:
        user_id = auth.get("user_id")
        logger.info(f"Getting messages for session {session_id} in agent {agent_id}")
        return await get_session_messages_data(session_id, agent_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting session messages: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

