"""MCP server exposing existing Database Agent capabilities as tools.

The tools are a presentation layer over the product REST API (see ``client.py``): the same
agent answers the question, with the same authentication, model configuration, table
visibility, SQL access controls and execution pipeline. Nothing here generates or runs SQL.
"""
from __future__ import annotations

import json
import logging
import sys
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Literal, Optional

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from .client import ApiError, DatabaseAgentApi
from .config import ConfigError, Settings

log = logging.getLogger("database_agent_mcp")

MAX_ROWS_LIMIT = 1000

INSTRUCTIONS = """\
Ask questions of SQL databases through FutureSmart Database Agent.
Start with list_agents to find the agent connected to the data you need, then call
ask_database with a natural-language question. Each answer returns the agent's text answer,
the SQL it generated and ran (when the agent allows showing it), the result rows and any
chart suggestion. Pass the returned session_id to ask_database to ask a follow-up in the same
conversation. list_conversations and get_conversation return saved conversations and results.
The agent runs read-only queries through its own access controls; it does not modify data.
Report the SQL and rows alongside the answer so the user can check it."""


# ── Structured outputs ──────────────────────────────────────────────────────────────────────

class Database(BaseModel):
    db_id: str
    name: Optional[str] = None
    engine: Optional[str] = None
    description: Optional[str] = None
    table_count: Optional[int] = None
    active: bool = True


class Agent(BaseModel):
    agent_id: str
    name: Optional[str] = None
    greeting: Optional[str] = None
    credential: Literal["agent_key", "operator_key"]
    shows_sql: bool = Field(description="Agent setting: generated SQL may be returned")
    shows_rows: bool = Field(description="Agent setting: result rows may be returned")
    databases: List[Database] = []


class UnavailableAgent(BaseModel):
    agent_id: str
    error: str


class AgentList(BaseModel):
    agents: List[Agent]
    unavailable: List[UnavailableAgent] = Field(
        default=[], description="Configured agents whose credential was refused or which could not be read")


class Column(BaseModel):
    name: str
    type: Optional[str] = None


class ResultRows(BaseModel):
    columns: List[Column]
    rows: List[Dict[str, Any]]
    row_count: int = Field(description="Rows produced by the SQL")
    returned: int = Field(description="Rows included here")
    truncated: bool = Field(description="True when rows were omitted (see max_rows)")


class Chart(BaseModel):
    type: Optional[str] = Field(None, description="Suggested chart type, e.g. bar or line")
    data: Any = None
    metadata: Any = None


class Answer(BaseModel):
    agent_id: str
    session_id: str = Field(description="Pass to ask_database to continue this conversation")
    chat_id: Optional[str] = None
    question: str
    answer: str
    answered: bool = Field(description="False when the agent could not answer from the connected data")
    sql: Optional[str] = Field(None, description="SQL the agent generated and ran; None if hidden or none ran")
    tables: List[str] = []
    database: Optional[str] = None
    result: Optional[ResultRows] = None
    chart: Optional[Chart] = None
    follow_up_questions: List[str] = []
    notes: List[str] = []


class ConversationSummary(BaseModel):
    session_id: str
    title: Optional[str] = None
    first_question: Optional[str] = None
    created: Optional[str] = None


class ConversationList(BaseModel):
    agent_id: str
    conversations: List[ConversationSummary]
    total: int


class SavedTurn(BaseModel):
    chat_id: Optional[str] = None
    question: Optional[str] = None
    answer: Optional[str] = None
    timestamp: Optional[str] = None
    sql: Optional[str] = None
    result: Optional[ResultRows] = None
    chart: Optional[Chart] = None
    feedback: Optional[str] = None


class Conversation(BaseModel):
    agent_id: str
    session_id: str
    title: Optional[str] = None
    created: Optional[str] = None
    turns: List[SavedTurn]
    notes: List[str] = []


# ── Shaping helpers (presentation only) ─────────────────────────────────────────────────────

def _rows(block: Any, max_rows: int) -> Optional[ResultRows]:
    if not isinstance(block, dict):
        return None
    rows = block.get("rows") or []
    columns = [Column(name=str(c.get("name")), type=c.get("type")) if isinstance(c, dict) else Column(name=str(c))
               for c in (block.get("columns") or [])]
    total = int(block.get("row_count") if block.get("row_count") is not None else len(rows))
    kept = rows[:max_rows]
    return ResultRows(columns=columns, rows=kept, row_count=total, returned=len(kept),
                      truncated=bool(block.get("truncated")) or len(kept) < total)


def _bare_rows(raw: Any, max_rows: int) -> Optional[ResultRows]:
    """Turns saved before per-turn result blocks existed keep rows without column names."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return None
    if not isinstance(raw, list):
        return None
    width = max((len(r) for r in raw if isinstance(r, (list, tuple))), default=1)
    names = [f"column_{i + 1}" for i in range(width)]
    rows = [dict(zip(names, r)) if isinstance(r, (list, tuple)) else (r if isinstance(r, dict) else {names[0]: r})
            for r in raw]
    return _rows({"columns": [{"name": n} for n in names], "rows": rows, "row_count": len(rows)}, max_rows)


def _chart(block: Any, max_rows: int) -> Optional[Chart]:
    if not isinstance(block, dict) or not any(block.get(k) is not None
                                              for k in ("chart_suggestion", "chart_data", "metadata")):
        return None
    data = block.get("chart_data")
    if isinstance(data, list):
        data = data[:max_rows]
    return Chart(type=block.get("chart_suggestion"), data=data, metadata=block.get("metadata"))


def _bounded(max_rows: int) -> int:
    if max_rows < 0:
        raise ToolError("max_rows must be 0 or more")
    return min(max_rows, MAX_ROWS_LIMIT)


def _tool_error(exc: Exception, agent_id: Optional[str] = None) -> ToolError:
    where = f" for agent {agent_id}" if agent_id else ""
    if isinstance(exc, ConfigError):
        return ToolError(str(exc))
    if isinstance(exc, ApiError):
        if exc.status == 401:
            return ToolError(f"Database Agent rejected the configured credential{where} (HTTP 401): {exc.detail}")
        if exc.status == 403:
            return ToolError(f"Not permitted{where} (HTTP 403): {exc.detail}")
        if exc.status == 404:
            return ToolError(f"Not found{where} (HTTP 404): {exc.detail}")
        if exc.status == 429:
            return ToolError(f"Query limit reached{where} (HTTP 429): {exc.detail}")
        if exc.code == "model_configuration_error":
            return ToolError(f"Agent model configuration error{where}: {exc.detail}")
        return ToolError(f"Database Agent API error{where} (HTTP {exc.status}): {exc.detail}")
    if isinstance(exc, httpx.TimeoutException):
        return ToolError("Database Agent did not respond in time; raise DATABASE_AGENT_TIMEOUT_SECONDS if "
                         "answers routinely take longer")
    if isinstance(exc, httpx.TransportError):
        return ToolError(f"Cannot reach the Database Agent API ({type(exc).__name__})")
    return ToolError(f"Unexpected error: {type(exc).__name__}")


# ── Server ──────────────────────────────────────────────────────────────────────────────────

def build_server(settings: Settings, transport: Optional[httpx.AsyncBaseTransport] = None) -> FastMCP:
    api = DatabaseAgentApi(settings, transport=transport)

    @asynccontextmanager
    async def lifespan(_server):
        try:
            yield {}
        finally:
            await api.aclose()

    mcp = FastMCP("database-agent", instructions=INSTRUCTIONS, lifespan=lifespan, log_level="WARNING")

    async def describe(agent: Dict[str, Any], credential: str) -> Agent:
        agent_id = agent["agent_id"]
        try:
            databases = [Database(db_id=d["db_id"], name=d.get("db_name"), engine=d.get("db_engine"),
                                  description=d.get("description"), table_count=d.get("table_count"),
                                  active=bool(d.get("is_active", True)))
                         for d in await api.list_databases(agent_id)]
        except ApiError:
            databases = []
        return Agent(agent_id=agent_id, name=agent.get("agent_name"), greeting=agent.get("greet_message"),
                     credential=credential, shows_sql=bool(agent.get("show_sql_query")),
                     shows_rows=bool(agent.get("show_db_result")), databases=databases)

    @mcp.tool(annotations=ToolAnnotations(title="List database agents", readOnlyHint=True, openWorldHint=False))
    async def list_agents() -> AgentList:
        """List the Database Agent agents this server's credentials can use, with their connected databases."""
        agents: List[Agent] = []
        unavailable: List[UnavailableAgent] = []
        seen = set()
        for agent_id in settings.agent_keys:
            try:
                agents.append(await describe(await api.get_agent(agent_id), "agent_key"))
            except Exception as exc:  # one refused key must not hide the others
                unavailable.append(UnavailableAgent(agent_id=agent_id, error=str(_tool_error(exc, agent_id))))
            seen.add(agent_id)
        if settings.operator_key:
            try:
                for agent in await api.list_all_agents():
                    if agent.get("agent_id") and agent["agent_id"] not in seen:
                        seen.add(agent["agent_id"])
                        agents.append(await describe(agent, "operator_key"))
            except Exception as exc:
                raise _tool_error(exc) from exc
        return AgentList(agents=agents, unavailable=unavailable)

    @mcp.tool(annotations=ToolAnnotations(title="Ask a database question", readOnlyHint=False,
                                          destructiveHint=False, idempotentHint=False, openWorldHint=False))
    async def ask_database(agent_id: str, question: str, session_id: Optional[str] = None,
                           include_chart: Optional[bool] = None, max_rows: int = 100) -> Answer:
        """Ask a Database Agent agent a natural-language question about its connected database.

        Returns the answer, the generated SQL, structured result rows and chart metadata.
        Omit session_id to start a new conversation; pass a previous answer's session_id to ask a
        follow-up with that conversation's context. include_chart defaults to the agent's setting.
        max_rows (default 100, up to 1000) limits the rows returned here, not the query itself.
        """
        if not question.strip():
            raise ToolError("question must not be empty")
        limit = _bounded(max_rows)
        try:
            body = await api.ask(agent_id, question, session_id=session_id, chart_output=include_chart)
        except Exception as exc:
            raise _tool_error(exc, agent_id) from exc

        debug = body.get("debug_info") or {}
        notes: List[str] = []
        if "sql_query" not in debug:
            notes.append("This agent's settings do not allow returning generated SQL.")
        if "db_result" not in debug:
            notes.append("This agent's settings do not allow returning result rows.")
        result = _rows(debug.get("db_result"), limit)
        if result and result.truncated:
            notes.append(f"Showing {result.returned} of {result.row_count} rows; raise max_rows for more.")
        if debug.get("export_url"):
            notes.append("A CSV export of the full result is available from the agent's export link.")
        return Answer(
            agent_id=agent_id, session_id=body.get("session_id") or session_id or "", chat_id=body.get("chat_id"),
            question=question, answer=body.get("response") or "", answered=bool(body.get("is_answered")),
            sql=debug.get("sql_query") or None, tables=debug.get("selected_tables") or [],
            database=debug.get("selected_db_name"), result=result,
            chart=_chart(body.get("chart_output"), limit), follow_up_questions=body.get("follow_up") or [],
            notes=notes,
        )

    @mcp.tool(annotations=ToolAnnotations(title="List saved conversations", readOnlyHint=True, openWorldHint=False))
    async def list_conversations(agent_id: str, limit: int = 20) -> ConversationList:
        """List saved conversations (sessions) on an agent, newest first."""
        try:
            sessions = await api.list_sessions(agent_id)
        except Exception as exc:
            raise _tool_error(exc, agent_id) from exc
        items = [ConversationSummary(session_id=s["session_id"], title=s.get("session_title"),
                                     first_question=s.get("display_message"),
                                     created=str(s["created_time"]) if s.get("created_time") else None)
                 for s in sessions if s.get("session_id")]
        return ConversationList(agent_id=agent_id, conversations=items[:max(limit, 0)], total=len(items))

    @mcp.tool(annotations=ToolAnnotations(title="Get a saved conversation", readOnlyHint=True, openWorldHint=False))
    async def get_conversation(agent_id: str, session_id: str, max_rows: int = 100) -> Conversation:
        """Return a saved conversation with each turn's question, answer, SQL, result rows and chart."""
        limit = _bounded(max_rows)
        try:
            agent = await api.get_agent(agent_id)
            body = await api.get_session(agent_id, session_id)
        except Exception as exc:
            raise _tool_error(exc, agent_id) from exc
        # The live chat route applies these agent settings server-side; apply the same
        # settings to the saved copy so both tools return the same visibility.
        shows_sql, shows_rows = bool(agent.get("show_sql_query")), bool(agent.get("show_db_result"))
        turns: Dict[str, SavedTurn] = {}
        order: List[str] = []
        for message in body.get("conversation_data") or []:
            key = message.get("chat_id") or f"#{len(order)}"
            if key not in turns:
                turns[key] = SavedTurn(chat_id=message.get("chat_id"), timestamp=message.get("timestamp"))
                order.append(key)
            turn = turns[key]
            if message.get("role") == "user":
                turn.question = message.get("message")
                continue
            turn.answer = message.get("message")
            turn.feedback = message.get("user_feedback")
            debug = message.get("debug_info") or {}
            if shows_sql:
                turn.sql = debug.get("sql_query") or None
            if shows_rows:
                turn.result = _rows(message.get("result"), limit) or _bare_rows(debug.get("db_output"), limit)
            turn.chart = _chart(message.get("graph_output"), limit)
        notes = []
        if not shows_sql:
            notes.append("This agent's settings do not allow returning generated SQL.")
        if not shows_rows:
            notes.append("This agent's settings do not allow returning result rows.")
        return Conversation(agent_id=agent_id, session_id=body.get("session_id") or session_id,
                            title=body.get("session_title"),
                            created=str(body["created_time"]) if body.get("created_time") else None,
                            turns=[turns[k] for k in order], notes=notes)

    return mcp


def main() -> None:
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr, format="%(name)s: %(message)s")
    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        print(f"database-agent-mcp: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    build_server(settings).run("stdio")


if __name__ == "__main__":
    main()
