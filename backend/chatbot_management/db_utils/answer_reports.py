"""Problem reports on one answer, made from the answer itself.

A person who gets a wrong or broken answer says what was wrong and what they expected. The
report is only useful if someone else can reproduce it later, so the server, not the
browser, attaches a snapshot of the conversation up to and including that answer, read from
`nl2sql_logs`: each question, how the agent restated it, the SQL, the answer text, the
number of rows and the first rows, and the chart. Earlier turns matter because follow-up
questions are answered in the context of the ones before them.

Only the person who asked the question can report it (`nl2sql_logs.user_id`), so a report
can never carry someone else's conversation.
"""
from __future__ import annotations

import json
import secrets
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

CATEGORIES = ("wrong_answer", "wrong_chart", "lost_context", "error", "slow", "other")
STATUSES = ("open", "triaged", "fixed", "not_a_bug")

NOTE_MAX = 4000
_ROWS_KEPT = 20
_ANSWER_MAX = 8000


class ReportError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _rows(db_output: Optional[str]) -> Dict[str, Any]:
    """Row count and the first rows of a stored result, whatever shape it was saved in."""
    if not db_output:
        return {"row_count": 0, "first_rows": []}
    try:
        rows = json.loads(db_output)
    except (TypeError, ValueError):
        return {"row_count": None, "first_rows": [], "raw": db_output[:2000]}
    if isinstance(rows, dict):
        rows = rows.get("rows") or rows.get("data") or [rows]
    if not isinstance(rows, list):
        return {"row_count": None, "first_rows": [], "raw": str(rows)[:2000]}
    return {"row_count": len(rows), "first_rows": rows[:_ROWS_KEPT]}


def _chart(graph_output: Any, chart_output: Any) -> Optional[Dict[str, Any]]:
    for value in (chart_output, graph_output):
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                continue
        if isinstance(value, dict) and value:
            return {k: value.get(k) for k in ("chart_suggestion", "graph_type", "chart_type", "type", "x_label",
                                                "y_label", "title") if value.get(k) is not None} \
                or {"present": True}
    return None


async def _snapshot(session: AsyncSession, *, agent_id: str, session_id: str, chat_id: str,
                    user_id: str) -> Dict[str, Any]:
    turns = (await session.execute(text("""
        select chat_id, query, refined_query, sql_query, db_output, response, graph_output,
               chart_output, is_answered, feedback, created_at, user_id
          from nl2sql_logs
         where session_id = :session_id and agent_id = :agent_id
         order by created_at, id
    """), {"session_id": session_id, "agent_id": agent_id})).all()
    index = next((i for i, t in enumerate(turns) if t.chat_id == chat_id), None)
    if index is None:
        raise ReportError(404, "That answer was not found in this conversation.")
    if (turns[index].user_id or "").strip().lower() != user_id:
        raise ReportError(403, "Only the person who asked this question can report it.")
    health = (await session.execute(text("""
        select route, status, failure_category, failed_stage, rows_returned, chart_generated,
               latency_ms, total_tokens, key_type
          from nl2sql_agent_health_events where chat_id = :chat_id
    """), {"chat_id": chat_id})).first()

    out: List[Dict[str, Any]] = []
    for t in turns[:index + 1]:
        turn = {
            "chat_id": t.chat_id,
            "asked_at": t.created_at.isoformat(timespec="seconds") + "Z" if t.created_at else None,
            "question": t.query,
            "restated_question": t.refined_query,
            "sql": t.sql_query,
            "answer": (t.response or "")[:_ANSWER_MAX],
            "is_answered": t.is_answered,
            "chart": _chart(t.graph_output, t.chart_output),
            "feedback": t.feedback,
        }
        turn.update(_rows(t.db_output))
        out.append(turn)
    snapshot: Dict[str, Any] = {"turns": out, "reported_turn": index + 1}
    if health is not None:
        snapshot["run"] = dict(health._mapping)
    return snapshot


async def create_report(session: AsyncSession, *, agent_id: str, session_id: str, chat_id: str,
                        user_id: str, category: str, note: str,
                        expected: Optional[str]) -> Dict[str, Any]:
    user_id = (user_id or "").strip().lower()
    note = (note or "").strip()
    expected = (expected or "").strip() or None
    if not user_id:
        raise ReportError(401, "Sign in to report a problem with an answer.")
    if category not in CATEGORIES:
        raise ReportError(400, "Unknown problem type.")
    if not note:
        raise ReportError(400, "Say what was wrong with the answer.")
    if len(note) > NOTE_MAX or (expected and len(expected) > NOTE_MAX):
        raise ReportError(400, f"Keep the description under {NOTE_MAX} characters.")
    snapshot = await _snapshot(session, agent_id=agent_id, session_id=session_id,
                               chat_id=chat_id, user_id=user_id)
    report_id = "RPT_" + secrets.token_hex(4).upper()
    await session.execute(text("""
        insert into nl2sql_answer_reports
          (report_id, agent_id, session_id, chat_id, user_id, category, note, expected, snapshot)
        values (:report_id, :agent_id, :session_id, :chat_id, :user_id, :category, :note,
                :expected, CAST(:snapshot AS jsonb))
    """), {"report_id": report_id, "agent_id": agent_id, "session_id": session_id,
           "chat_id": chat_id, "user_id": user_id, "category": category, "note": note,
           "expected": expected, "snapshot": json.dumps(snapshot, default=str)})
    await session.commit()
    return {"report_id": report_id, "status": "open"}


async def list_reports(session: AsyncSession, *, agent_id: Optional[str] = None,
                       status: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
    where: List[str] = []
    params: Dict[str, Any] = {"limit": max(1, min(int(limit), 200))}
    if agent_id:
        where.append("agent_id = :agent_id")
        params["agent_id"] = agent_id
    if status:
        where.append("status = :status")
        params["status"] = status
    clause = ("where " + " and ".join(where)) if where else ""
    rows = (await session.execute(text(f"""
        select report_id, agent_id, session_id, chat_id, user_id, category, note, expected,
               snapshot, status, created_at
          from nl2sql_answer_reports {clause}
         order by created_at desc
         limit :limit
    """), params)).all()
    total = (await session.execute(text(
        f"select count(*) from nl2sql_answer_reports {clause}"),
        {k: v for k, v in params.items() if k != "limit"})).scalar_one()
    return {
        "total": int(total),
        "reports": [{**dict(r._mapping),
                     "created_at": r.created_at.isoformat(timespec="seconds") + "Z"}
                    for r in rows],
    }


async def set_report_status(session: AsyncSession, report_id: str, status: str) -> bool:
    if status not in STATUSES:
        raise ReportError(400, "Unknown report status.")
    result = await session.execute(text("""
        update nl2sql_answer_reports set status = :status where report_id = :report_id
    """), {"status": status, "report_id": report_id})
    await session.commit()
    return result.rowcount > 0
