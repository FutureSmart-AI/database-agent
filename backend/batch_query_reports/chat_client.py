"""Ask an NL2SQL agent one question, on behalf of a report run.

The in-process executor deliberately goes through this service's own HTTP chat endpoint
(`POST /v1/agents/{agent_id}/chat`) rather than calling the agent graph directly. That
endpoint is where session history, `nl2sql_logs` persistence, the S3 CSV export and chart
generation are wired together; reaching past it would mean duplicating that orchestration and
letting the two copies drift. The cost is one loopback request per query.

`debug_info=true` is what makes the executed SQL and the result table available — without it
the chat response carries only prose. Note the agent's own `show_sql_query` / `show_db_result`
visibility flags still apply, so an agent configured to hide its SQL produces a report without
SQL, by design.
"""
import time
from typing import Any, Dict, Optional, Tuple

import httpx

from logger import logger

from batch_query_reports import reports_env


def _url(agent_id: str) -> str:
    base = (reports_env.REPORTS_CHAT_BASE or "").rstrip("/")
    return f"{base}/v1/agents/{agent_id}/chat"


def _headers() -> Dict[str, str]:
    # The master key: a background run has no browser session to borrow, and chat is
    # agent-scoped. Being a master-key caller is also what lets us declare the end user via
    # `user_id` in the body (see chat_with_agent).
    return {
        "X-API-Key": reports_env.FASTAPI_SECRET_KEY or "",
        "Content-Type": "application/json",
    }


def _compose_query(question: str, report_instructions: Optional[str]) -> str:
    """Fold report-level instructions into the question.

    `ChatRequest` has no instructions field and ignores unknown ones, so prefixing the query
    is the only way to apply them — and it keeps them visible in `nl2sql_logs`, where the turn
    is recorded exactly as the agent saw it.
    """
    if not report_instructions:
        return question
    return f"{report_instructions.strip()}\n\n{question}"


def _execution_details(body: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Pull the NL2SQL execution trace out of a chat response.

    Assembled from `debug_info` (SQL, tables, result table, export link, routed database) and
    `chart_output`, into the shape the report view and the exporters read. Returns None when
    the response carries neither — nothing useful to show.
    """
    debug = body.get("debug_info") or {}
    chart = body.get("chart_output") or {}
    if not isinstance(debug, dict):
        debug = {}
    if not isinstance(chart, dict):
        chart = {}
    if not debug and not chart:
        return None

    return {
        "sql_query": debug.get("sql_query"),
        # `selected_tables` is already narrowed to the tables the emitted SQL references.
        "tables_used": debug.get("selected_tables") or [],
        "db_result": debug.get("db_result"),
        "export_url": debug.get("export_url"),
        "refined_query": debug.get("refined_query"),
        "selected_db_id": debug.get("selected_db_id"),
        "selected_db_name": debug.get("selected_db_name"),
        "cross_db": debug.get("cross_db"),
        "chart_suggestion": chart.get("chart_suggestion"),
        "chart_data": chart.get("chart_data"),
    }


async def _fetch_token_usage(chat_id: Optional[str]) -> Optional[int]:
    """Token count for a turn, read from `nl2sql_logs`.

    The chat response does not carry token usage, but the endpoint has already written the log
    row (persistence is awaited before it replies), so the number is available by `chat_id`.
    Best-effort: a report should never fail over a missing metric.
    """
    if not chat_id:
        return None
    try:
        from sqlmodel import select

        from agent.services.sqlmodel_session import async_session
        from models.sql_models import ChatLogs

        async with async_session() as session:
            row = (await session.execute(
                select(ChatLogs.tokens_consumed).where(ChatLogs.chat_id == chat_id)
            )).first()
        if not row or row[0] in (None, ""):
            return None
        return int(float(row[0]))
    except Exception as e:
        logger.debug(f"[reports.chat] token usage lookup failed for chat_id={chat_id}: {e}")
        return None


def _empty_envelope() -> Dict[str, Any]:
    return {
        "answer": "",
        "session_id": None,
        "chat_id": None,
        "execution_details": None,
        "is_answered": None,
        "token_usage": None,
    }


async def ask_agent(
    *,
    agent_id: str,
    question: str,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    report_instructions: Optional[str] = None,
) -> Tuple[Dict[str, Any], Optional[str]]:
    """Send one question to the agent.

    Returns `(envelope, error)`. The envelope always has every key the result contract needs,
    so a partial or broken response still produces a storable row. On failure `error` is a
    non-empty string and `answer` is empty — the runner writes both, and the query is counted
    as failed rather than silently missing.
    """
    payload: Dict[str, Any] = {
        "query": _compose_query(question, report_instructions),
        # Required for the executed SQL and the result table to come back at all.
        "debug_info": True,
        "chart_output": True,
        # Follow-up suggestions are for interactive users; generating them here would spend a
        # model call per query for something no one reads.
        "follow_up": False,
    }
    if session_id:
        payload["session_id"] = session_id
    if user_id:
        # Honored because we authenticate with the master key: the run is attributed to the
        # user who owns it, so its turns land under them in nl2sql_logs.
        payload["user_id"] = user_id

    start = time.monotonic()
    error: Optional[str] = None
    body: Dict[str, Any] = {}
    try:
        timeout = httpx.Timeout(
            float(reports_env.REPORTS_QUERY_TIMEOUT_SECONDS), connect=10.0
        )
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(_url(agent_id), headers=_headers(), json=payload)
        if resp.status_code != 200:
            error = f"chat endpoint {resp.status_code}: {resp.text[:300]}"
            logger.warning(f"[reports.chat] ask_agent failed ({error})")
        else:
            try:
                body = resp.json() or {}
            except ValueError as e:
                error = f"chat endpoint returned non-JSON: {e}"
                logger.warning(f"[reports.chat] {error}")
    except httpx.TimeoutException:
        error = f"chat endpoint timed out after {reports_env.REPORTS_QUERY_TIMEOUT_SECONDS}s"
        logger.warning(f"[reports.chat] {error}")
    except httpx.HTTPError as e:
        error = f"chat endpoint request error: {e}"
        logger.warning(f"[reports.chat] {error}")

    elapsed_ms = int((time.monotonic() - start) * 1000)

    envelope = _empty_envelope()
    if body:
        envelope.update({
            "answer": body.get("response") or "",
            "session_id": body.get("session_id"),
            "chat_id": body.get("chat_id"),
            "execution_details": _execution_details(body),
            "is_answered": body.get("is_answered"),
            "token_usage": await _fetch_token_usage(body.get("chat_id")),
        })
        # An agent that answered nothing is a failed query even on HTTP 200 — otherwise the
        # report would show a blank answer and count it as a success.
        if not error and not envelope["answer"]:
            error = "agent returned an empty answer"

    envelope["response_time_ms"] = elapsed_ms
    return envelope, error
