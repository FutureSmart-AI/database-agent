from typing import Optional, List, Dict, Any, Tuple
import re
import time
import json
import uuid
import traceback
import os
from fastapi import HTTPException
from chatbot_management.services.logger import logger
from agent.db_utils.session_db_utils import log_new_session as agent_log_new_session
from agent.db_utils.common_db_utils import upload_to_db_nl2sql_logs
from agent.runner import run_agent_flow
from agent.utils.follow_up import generate_follow_up_questions
from agent.utils.common_utils import serialize_db_result, build_data_block
from models.sql_models import ChatLogs, ChatbotDetails
from chatbot_management.services.sqlmodel_session import get_async_session
from sqlmodel import select


async def get_past_conversation_safe(session_id):
    """Get past conversation for a session"""
    try:
        start_time = time.time()
        messages = []
        async for session in get_async_session():
            res = await session.execute(
                select(ChatLogs).where(ChatLogs.session_id == session_id).order_by(ChatLogs.created_at)
            )
            rows = res.scalars().all()
            for chat_log in rows:
                if chat_log.user_query:
                    messages.append({"role": "user", "content": chat_log.user_query})
                if chat_log.gpt_response:
                    messages.append({"role": "assistant", "content": chat_log.gpt_response})
        logger.info(f"History retrieved: {len(messages)} messages")
        return messages
    except Exception as e:
        logger.error(f"Error getting past conversation: {e}")
        return []


async def get_past_messages_safe(session_id, user_id, agent_id, user_query):
    try:
        if not session_id or session_id in ["", "string"]:
            session_info = await agent_log_new_session(user_id, agent_id, user_query)
            return {"past_messages": [], "session_id": session_info['session_id']}
        else:
            past_messages = await get_past_conversation_safe(session_id)
            return {"past_messages": past_messages, "session_id": session_id}
    except Exception as e:
        logger.error(f"Error in get_past_messages_safe: {str(e)}")
        return {"past_messages": [], "session_id": session_id}


async def ensure_session_belongs_to_agent(session_id: Optional[str], agent_id: str) -> None:
    """Refuse to continue a session that was not created on this agent.

    History is read by session_id alone (get_past_conversation_safe), so an unchecked id would
    replay another agent's questions and answers into this agent's model context and append the
    new turn to that foreign session. A new conversation (no id) is always allowed.
    """
    if not session_id or session_id in ["", "string"]:
        return
    from session.db_utils.session_db_utils import get_session_details
    if not await get_session_details(session_id, agent_id):
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found for agent {agent_id}")


async def get_owner_email_by_agent_id(agent_id: str) -> Optional[str]:
    try:
        async for session in get_async_session():
            res = await session.execute(
                select(ChatbotDetails.owner_id).where(ChatbotDetails.agent_id == agent_id).limit(1)
            )
            row = res.first()
            if row is None:
                return None
            return row if isinstance(row, str) else (row[0] if isinstance(row, tuple) else getattr(row, "owner_id", None))
    except Exception:
        return None


async def prepare_chat_response(
    agent_id: str,
    body: Any,
    user_id: str,
    owner_email: str,
    past_messages: List[Dict],
    session_id: str,
    request_id: str,
    chat_id: str,
    runtime_db: Dict,
    db_fetch_elapsed: float
) -> Dict[str, Any]:
    """Core logic to run the agent flow and prepare a non-streaming response"""
    agent_start_time = time.time()

    result = await run_agent_flow(
        query=body.query,
        past_messages=past_messages,
        table_descriptions=None,
        runtime_db_details=runtime_db,
        selected_tables=None,
        few_shot_examples=None,
        user_id=user_id,
        owner_id=owner_email,
        agent_id=agent_id,
        allowed_graphs=body.allowed_charts,
        include_graph_output=bool(body.chart_output),
        session_id=session_id,
        request_id=request_id,
    )

    agent_elapsed = time.time() - agent_start_time
    final_text = result.get("response", "")

    # Optional follow-up question generation
    follow_up_questions = None
    if getattr(body, "follow_up", False):
        try:
            follow_up_questions = await generate_follow_up_questions(
                owner_id=owner_email,
                agent_id=agent_id,
                messages=past_messages,
                refined_query=result.get("refined_query", body.query),
                response=final_text,
                follow_up_context=None,
            )
        except Exception as fu_err:
            logger.error(f"Follow-up generation failed: {fu_err}")

    # Persist logs
    chart_output_payload = format_chart_output_payload(result, bool(body.chart_output))
    await upload_to_db_nl2sql_logs(
        session_id, user_id, agent_id, chat_id, body.query,
        result.get("refined_query", body.query), result.get("sql_query", ""),
        result.get("db_result", []), final_text, chart_output_payload,
        agent_elapsed, db_fetch_elapsed, result.get("total_tokens", 0),
        bool(body.chart_output), bool(body.debug_info)
    )

    # Build final response
    final_response = {
        "response": final_text,
        "session_id": session_id,
        "chat_id": chat_id,
        "follow_up": follow_up_questions,
        "debug_info": format_debug_info(result, body) if body.debug_info else None,
        "chart_output": format_chart_output(result) if body.chart_output else None
    }

    return final_response


def format_chart_output_payload(result: Dict, chart_output: bool) -> Optional[str]:
    """Format chart JSON for database logging"""
    if not chart_output:
        return None

    graph_json = result.get("graph_json")
    if graph_json and (graph_json.get("graph_suggestion") or graph_json.get("graph_data") or graph_json.get("metadata")):
        return json.dumps(graph_json)
    else:
        return json.dumps({"post_processing_query": result.get("post_processing_query")})


def format_debug_info(result: Dict, body: Any) -> Dict[str, Any]:
    """Format debug information for the response"""
    return {
        "query": body.query,
        "refined_query": result.get("refined_query", body.query),
        "sql_query": result.get("sql_query", ""),
        "db_result": serialize_db_result(result.get("db_result", [])),
        "selected_tables": result.get("selected_tables")
    }


def format_chart_output(result: Dict) -> Optional[Dict[str, Any]]:
    """Format chart output for the response"""
    graph_json = result.get("graph_json")
    if graph_json and (graph_json.get("graph_suggestion") or graph_json.get("graph_data") or graph_json.get("metadata")):
        return {
            "chart_suggestion": graph_json.get("graph_suggestion"),
            "chart_data": graph_json.get("graph_data"),
            "metadata": graph_json.get("metadata"),
        }
    return None


async def agent_stream_generator(
    agent_id: str,
    body: Any,
    user_id: str,
    owner_email: str,
    past_messages: List[Dict],
    session_id: str,
    request_id: str,
    chat_id: str,
    runtime_db: Dict,
    db_fetch_elapsed: float
):
    """Generator for streaming chat responses"""
    try:
        agent_start_time = time.time()

        result = await run_agent_flow(
            query=body.query,
            past_messages=past_messages,
            table_descriptions=None,
            runtime_db_details=runtime_db,
            selected_tables=None,
            few_shot_examples=None,
            user_id=user_id,
            owner_id=owner_email,
            agent_id=agent_id,
            allowed_graphs=body.allowed_charts,
            include_graph_output=bool(body.chart_output),
            session_id=session_id,
            request_id=request_id,
        )

        agent_elapsed = time.time() - agent_start_time
        final_text = result.get("response", "")

        # Follow-up generation
        follow_up_questions = None
        if getattr(body, "follow_up", False):
            try:
                follow_up_questions = await generate_follow_up_questions(
                    owner_id=owner_email,
                    agent_id=agent_id,
                    messages=past_messages,
                    refined_query=result.get("refined_query", body.query),
                    response=final_text,
                    follow_up_context=None,
                )
            except Exception as fu_err:
                logger.error(f"Follow-up generation failed: {fu_err}")

        # Stream chunks (sentences)
        for sentence in filter(None, [s.strip() for s in final_text.split('.')]):
            yield f"data: {json.dumps({'chunk': sentence + '.', 'session_id': session_id})}\n\n"

        # Persist logs
        chart_output_payload = format_chart_output_payload(result, bool(body.chart_output))
        await upload_to_db_nl2sql_logs(
            session_id, user_id, agent_id, chat_id, body.query,
            result.get("refined_query", body.query), result.get("sql_query", ""),
            result.get("db_result", []), final_text, chart_output_payload,
            agent_elapsed, db_fetch_elapsed, result.get("total_tokens", 0),
            bool(body.chart_output), bool(body.debug_info)
        )

        # Send final metadata
        final_response = {
            "response": final_text,
            "session_id": session_id,
            "chat_id": chat_id,
            "follow_up": follow_up_questions,
            "debug_info": format_debug_info(result, body) if body.debug_info else None,
            "chart_output": format_chart_output(result) if body.chart_output else None
        }
        yield f"full_metadata: {json.dumps(final_response)}\n\n"

    except Exception as e:
        logger.error(f"Streaming error: {str(e)}")
        traceback.print_exc()
        yield f"full_metadata: {json.dumps({'error': str(e)})}\n\n"


async def get_agent_with_visibility(agent_id: str):
    """Fetch agent and return (agent_obj, show_sql_query, show_db_result, include_debug_block)"""
    async for session in get_async_session():
        result = await session.execute(
            select(ChatbotDetails).where(ChatbotDetails.agent_id == agent_id)
        )
        agent = result.scalar_one_or_none()
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    _sql_flag = getattr(agent, "show_sql_query", None)
    _data_flag = getattr(agent, "show_db_result", None)
    show_sql_query = True if _sql_flag is None else bool(_sql_flag)
    show_db_result = True if _data_flag is None else bool(_data_flag)
    include_debug_block = show_sql_query or show_db_result
    return agent, show_sql_query, show_db_result, include_debug_block


# Chat request field -> (column on chatbot_details, value to use when the column is NULL).
# The dashboard's Settings screen writes these columns via PATCH /v1/agents/{id}/config/params;
# without this mapping the runtime never read them and the toggles had no effect on the answer.
ANSWER_SETTING_FALLBACKS = {
    "debug_info": ("debug_info", False),
    "chart_output": ("graph_output", True),
    "follow_up": ("follow_up", False),
    "allowed_charts": ("allowed_graphs", None),
}


def apply_agent_answer_settings(agent, body) -> Dict[str, Any]:
    """Fill any per-request answer flag the caller omitted from the agent's saved setting.

    Mutates `body` in place so every downstream consumer (the agent flow, build_chat_response,
    persist_chat_logs) sees one resolved value. An explicit request value always wins, so callers
    that send all four flags behave exactly as before.

    Returns the effective values, for logging.
    """
    effective = {}
    for request_field, (column, when_null) in ANSWER_SETTING_FALLBACKS.items():
        value = getattr(body, request_field, None)
        if value is None:
            stored = getattr(agent, column, None)
            value = when_null if stored is None else stored
            setattr(body, request_field, value)
        effective[request_field] = value
    return effective


async def get_agent_runtime_db(agent_id: str) -> Tuple[dict, float]:
    """Fetch DB connection details for an agent. Returns (db_details_dict, fetch_elapsed_seconds)."""
    from agent.db_utils.database_db_utils import get_db_connection as _get_db_conn
    start = time.time()
    db_response = await _get_db_conn(None, agent_id)
    elapsed = time.time() - start
    if not db_response.get("status") or not db_response.get("db_details"):
        error_message = db_response.get("message", f"Database connection not configured for agent {agent_id}")
        raise HTTPException(status_code=500, detail=error_message)
    return db_response.get("db_details"), elapsed


async def get_chat_log_for_export(session_id: str, chat_id: Optional[str]):
    """Fetch the ChatLogs row for a CSV export request."""
    async for db_session in get_async_session():
        if chat_id:
            res = await db_session.execute(
                select(ChatLogs).where(
                    ChatLogs.chat_id == chat_id,
                    ChatLogs.session_id == session_id,
                ).limit(1)
            )
        else:
            res = await db_session.execute(
                select(ChatLogs).where(
                    ChatLogs.session_id == session_id,
                    ChatLogs.sql_query.isnot(None),
                ).order_by(ChatLogs.created_at.desc()).limit(1)
            )
        return res.scalar_one_or_none()


async def get_session_messages_data(session_id: str, agent_id: str) -> dict:
    """Verify agent exists then return session conversation data."""
    async for session in get_async_session():
        result = await session.execute(
            select(ChatbotDetails).where(ChatbotDetails.agent_id == agent_id)
        )
        agent = result.scalar_one_or_none()
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    from session.db_utils.session_db_utils import get_session_data, get_session_details
    session_detail = await get_session_details(session_id, agent_id)
    if not session_detail:
        return {"message": "No session data found"}
    session_data = await get_session_data(session_id)
    if session_data:
        return {
            "session_id": session_detail['session_id'],
            "session_title": session_detail['session_title'],
            "created_time": session_detail['created_time'],
            "conversation_data": session_data
        }
    return {"message": "No conversation data found"}


def _tables_referenced_in_sql(candidate_tables: Optional[List[str]], sql_query: Optional[str]) -> List[str]:
    """Filter candidate (selected) tables down to the ones actually referenced in the
    generated SQL. `selected_tables` reflects the table-selection step, which — with no
    table descriptions configured — falls back to every table in the DB, so surfacing it
    as-is in "sources" misrepresents what the query actually used. If there's no SQL to
    check against (e.g. no query was generated), fall back to the candidate list unchanged
    since usage can't be determined either way.
    """
    if not candidate_tables:
        return candidate_tables or []
    if not sql_query:
        return candidate_tables

    used = []
    for table in candidate_tables:
        # Match the bare table name (last segment of a possibly schema-qualified name),
        # as a whole word, so it still matches when quoted (`"tbl"`, `` `tbl` ``, [tbl])
        # or schema-prefixed (schema.tbl) in the generated SQL.
        bare_name = table.split(".")[-1]
        pattern = r"(?<![A-Za-z0-9_])" + re.escape(bare_name) + r"(?![A-Za-z0-9_])"
        if re.search(pattern, sql_query, flags=re.IGNORECASE):
            used.append(table)
    return used


def build_chat_response(
    result: dict, body: Any, session_id: str, chat_id: str,
    show_sql_query: bool, show_db_result: bool,
    export_url: Optional[str] = None
) -> dict:
    """Build the standard non-streaming or streaming final response dict."""
    final_text = result.get("response", "")
    follow_up_questions = result.get("follow_up_questions")

    # is_answered is set by the final_answer node. For paths that bypass it (router END,
    # hard errors), fall back to: answered unless an error was surfaced or there's no text.
    is_answered = result.get("is_answered")
    if is_answered is None:
        is_answered = bool(final_text) and not (result.get("error") or result.get("sql_error"))

    final_response = {
        "response": final_text,
        "session_id": session_id,
        "chat_id": chat_id,
        "follow_up": follow_up_questions,
        "is_answered": bool(is_answered),
        # LangSmith trace id (None when tracing is disabled / unavailable).
        "trace_id": result.get("trace_id"),
    }

    # `debug_info` (request-level) is the master switch: no debug info at all when it's
    # off. The agent-level `show_sql_query` / `show_db_result` flags only control which
    # fields appear inside the block — query and refined_query are always included.
    if getattr(body, "debug_info", False):
        # Surface which database the DB router selected (multi-DB routing observability).
        _rt = result.get("runtime_db_details") or {}
        debug_block = {
            "query": body.query,
            "refined_query": result.get("refined_query", body.query),
            "selected_db_id": result.get("db_id") or _rt.get("db_id"),
            "selected_db_name": _rt.get("db_name"),
        }
        # Cross-DB routing observability (multi-db-spec.md §11): when a question was answered by
        # combining multiple databases, surface the flag and the DBs that were fanned out to.
        if result.get("cross_db"):
            debug_block["cross_db"] = True
            debug_block["selected_db_ids"] = [
                d.get("db_id") for d in (result.get("selected_dbs") or [])
            ]
        if show_sql_query:
            sql_query = result.get("sql_query", "")
            debug_block["sql_query"] = sql_query
            if result.get("access_denied_tables"):
                # sql_exec blocked the query for reading a table switched off in Tables &
                # visibility, and cleared the SQL. No table was read, so "sources" is empty —
                # _tables_referenced_in_sql would otherwise fall back to the candidate list,
                # which is its behaviour for "no SQL to check against", not for "nothing ran".
                debug_block["selected_tables"] = []
            else:
                debug_block["selected_tables"] = _tables_referenced_in_sql(
                    result.get("selected_tables"), sql_query
                )
        if show_db_result:
            debug_block["db_result"] = build_data_block(
                result.get("db_columns"),
                result.get("db_result"),
                row_limit=None,
            )
            if export_url:
                debug_block["export_url"] = export_url
        final_response["debug_info"] = debug_block
    else:
        final_response["debug_info"] = None

    graph_json = result.get("graph_json")
    if body.chart_output and graph_json and (
        graph_json.get("graph_suggestion") is not None
        or graph_json.get("graph_data") is not None
        or graph_json.get("metadata") is not None
    ):
        final_response["chart_output"] = {
            "chart_suggestion": graph_json.get("graph_suggestion"),
            "chart_data": graph_json.get("graph_data"),
            "metadata": graph_json.get("metadata"),
        }
    else:
        final_response["chart_output"] = None

    # The dashboard draws charts from `graph_output` and ignores `chart_output`, which is
    # why a live answer has never rendered one — it only ever sent `chart_output`. Same
    # object under both names: `chart_output` stays for any consumer already reading it.
    final_response["graph_output"] = final_response["chart_output"]

    return final_response


async def maybe_upload_csv_export(result: dict, agent_id: str, session_id: str, chat_id: str) -> Optional[str]:
    """Upload result rows to S3 if they exceeded the inline threshold. Returns presigned URL or None."""
    _db_cols = result.get("db_columns") or []
    _db_rows = result.get("db_result") or []
    _total_rows = len(_db_rows)
    _threshold = int(os.getenv("FINAL_ANSWER_TOP_N_CAP", "50"))
    _preview_limit = int(os.getenv("FINAL_ANSWER_INLINE_ROW_LIMIT", "10"))
    _effective_inline = _total_rows if _total_rows <= _threshold else _preview_limit
    if _db_cols and _total_rows > _effective_inline:
        try:
            from agent.utils.s3_export_utils import upload_csv_to_s3, generate_export_presigned_url, build_export_s3_key
            _s3_key = build_export_s3_key(agent_id, session_id, chat_id)
            if await upload_csv_to_s3(_db_cols, _db_rows, _s3_key):
                return await generate_export_presigned_url(_s3_key)
        except Exception as _e:
            logger.warning(f"S3 export failed (non-blocking): {_e}")
    return None


def _blocks_to_store(result: dict, body: Any) -> Tuple[Optional[dict], Optional[dict]]:
    """The (debug, chart) blocks to persist for this turn, for LATER replay.

    Deliberately duplicates the shaping in `build_chat_response` rather than sharing a
    helper with it. Sharing meant editing the live response builder, and reshaping that
    payload is exactly what took the dashboard's Data / Sources / Execution panels down.
    The live builder is left untouched; when a reader is added additively this can be
    folded back together and the duplication removed.

    Two differences from the live block, both intentional:

    * Built unconditionally, ignoring `debug_info` / `show_sql_query` / `show_db_result`.
      Those are display policy — a turn logged while a toggle was off should not be
      permanently missing its SQL, because the toggle can be turned on tomorrow and the
      turn cannot be re-run. Whatever serves this later applies the settings then.
    * No `export_url`: it is a short-lived presigned link and would be expired by the
      time anyone replayed it.
    """
    runtime = result.get("runtime_db_details") or {}
    sql_query = result.get("sql_query", "")
    debug_block = {
        "query": body.query,
        "refined_query": result.get("refined_query", body.query),
        "selected_db_id": result.get("db_id") or runtime.get("db_id"),
        "selected_db_name": runtime.get("db_name"),
        "sql_query": sql_query,
        "selected_tables": _tables_referenced_in_sql(result.get("selected_tables"), sql_query),
        "db_result": build_data_block(
            result.get("db_columns"), result.get("db_result"), row_limit=None
        ),
    }
    if result.get("cross_db"):
        debug_block["cross_db"] = True
        debug_block["selected_db_ids"] = [
            d.get("db_id") for d in (result.get("selected_dbs") or [])
        ]

    graph_json = result.get("graph_json") or {}
    has_chart = any(
        graph_json.get(k) is not None
        for k in ("graph_suggestion", "graph_data", "metadata")
    )
    chart_block = {
        "chart_suggestion": graph_json.get("graph_suggestion"),
        "chart_data": graph_json.get("graph_data"),
        "metadata": graph_json.get("metadata"),
    } if has_chart else None

    return debug_block, chart_block


async def persist_chat_logs(
    session_id: str, user_id: str, agent_id: str, chat_id: str,
    body: Any, result: dict, agent_elapsed: float, db_fetch_elapsed: float,
    include_debug_block: bool
) -> None:
    """Persist NL2SQL logs to database.

    Also stores the built answer blocks (`debug_info` / `chart_output`) for later replay.
    Nothing serves them yet — see `_blocks_to_store`.
    """
    from agent.db_utils.common_db_utils import upload_to_db_nl2sql_logs
    graph_output_payload = None
    if body.chart_output:
        graph_json = result.get("graph_json")
        if graph_json and (graph_json.get("graph_suggestion") or graph_json.get("graph_data") or graph_json.get("metadata")):
            graph_output_payload = json.dumps(graph_json)
        else:
            graph_output_payload = json.dumps({"post_processing_query": result.get("post_processing_query")})
    # Mirror build_chat_response: use the flag from final_answer, else fall back.
    _final_text = result.get("response", "")
    is_answered = result.get("is_answered")
    if is_answered is None:
        is_answered = bool(_final_text) and not (result.get("error") or result.get("sql_error"))

    await upload_to_db_nl2sql_logs(
        session_id, user_id, agent_id, chat_id, body.query,
        result.get("refined_query", body.query), result.get("sql_query", ""),
        result.get("db_result", []), result.get("response", ""),
        graph_output_payload, agent_elapsed, db_fetch_elapsed,
        result.get("total_tokens", 0), bool(body.chart_output), include_debug_block,
        bool(is_answered), *_blocks_to_store(result, body),
    )


async def persist_health_event(
    session_id: str, user_id: str, agent_id: str, chat_id: str, request_id: str,
    result: dict, agent_elapsed: float, db_fetch_elapsed: float,
    owner_email: Optional[str] = None, auth_type: Optional[str] = None,
    error: Optional[BaseException] = None,
) -> None:
    """Write this query's Agent Health row (analytics), next to the chat transcript row.

    Runs concurrently with persist_chat_logs and is deliberately independent of it: the
    conversation must be stored whether or not analytics succeeds, and vice versa. Never
    raises — send_query_event swallows everything, and this guard covers the argument
    marshalling too.
    """
    try:
        from agent.utils.agent_health_service import send_query_event
        await send_query_event(
            result=result or {},
            agent_id=agent_id,
            owner_id=owner_email,
            user_id=user_id,
            session_id=session_id,
            chat_id=chat_id,
            request_id=request_id,
            latency_ms=int((agent_elapsed or 0) * 1000),
            db_fetch_ms=int((db_fetch_elapsed or 0) * 1000),
            # Widget traffic authenticates with the agent's own key, not a dashboard
            # session — that's what separates end-user questions from operator testing.
            from_widget=(auth_type == "agent_api_key"),
            # key_type is NOT auth_type: it records whose LLM credentials paid, and is
            # rolled up from the nodes inside send_query_event. Passing the caller's auth
            # method here filled the column with "session" / "agent_api_key" instead, which
            # is the dimension from_widget above already carries.
            error=error,
        )
    except Exception as e:
        logger.error(f"Health event persistence failed (non-blocking): {e}")
