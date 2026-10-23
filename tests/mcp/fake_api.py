"""Synthetic stand-in for the Database Agent REST API, for MCP adapter contract tests.

It reproduces the response shapes and the credential rules the adapter relies on (operator
key reaches every agent; an agent key reaches only its own agent and no agent-less route;
sessions continue only on the agent that created them). Product behaviour itself is verified
against the real API; see docs/mcp.md.
"""
import json
import re
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

OPERATOR_KEY = "synthetic-operator-key"
AGENT_KEYS = {"key-sales": "NL2SQL_SALES", "key-hidden": "NL2SQL_HIDDEN"}
AGENTS = {
    "NL2SQL_SALES": {"agent_id": "NL2SQL_SALES", "agent_name": "Sales", "greet_message": "Hi",
                     "show_sql_query": True, "show_db_result": True, "system_prompt": "private"},
    "NL2SQL_HIDDEN": {"agent_id": "NL2SQL_HIDDEN", "agent_name": "Hidden SQL", "greet_message": None,
                      "show_sql_query": False, "show_db_result": False},
    "NL2SQL_OTHER": {"agent_id": "NL2SQL_OTHER", "agent_name": "Other", "greet_message": None,
                     "show_sql_query": True, "show_db_result": True},
}
SQL = "SELECT region, SUM(amount) AS total FROM orders GROUP BY region ORDER BY region"
ROWS = [{"region": "North", "total": "250.00"}, {"region": "South", "total": "200.00"}]


class FakeApi:
    def __init__(self):
        self.sessions = {}  # session_id -> {"agent_id": ..., "turns": [...]}
        self.requests = []  # (method, path, credential kind) — never the key itself
        self.limited = set()

    def auth(self, key, agent_id):
        if key == OPERATOR_KEY:
            return "operator", None
        if key in AGENT_KEYS:
            if not agent_id:
                return None, (401, "This API key is agent-scoped and cannot be used on this endpoint")
            if AGENT_KEYS[key] != agent_id:
                return None, (403, "This API key is not valid for this agent")
            return "agent", None
        return None, (401, "Not authenticated: valid session or API key required")

    def handle(self, method, path, key, body):
        path = path.split("?", 1)[0]
        match = re.match(r"^/nl2sql/api/v1/agents(?:/([^/]+))?(/.*)?$", path)
        if not match:
            return 404, {"detail": "Not Found"}
        agent_id, rest = match.group(1), match.group(2) or ""
        kind, error = self.auth(key, agent_id)
        self.requests.append((method, path, kind))
        if error:
            return error[0], {"detail": error[1]}
        if agent_id and agent_id not in AGENTS:
            return 404, {"detail": f"Agent with ID {agent_id} not found"}
        if method == "GET" and not agent_id:
            agents = list(AGENTS.values())
            return 200, {"owned_agents": agents[:2], "invited_agents": agents[2:],
                         "pagination": {"total": 3, "page": 1, "limit": 100, "pages": 1}}
        if method == "GET" and rest == "":
            return 200, {"data": AGENTS[agent_id]}
        if method == "GET" and rest == "/databases":
            return 200, {"data": [{"db_id": "db-1", "db_name": "sample_sales", "db_engine": "postgresql",
                                   "db_host": "sample-db", "db_user": "sample_reader", "db_password": "***",
                                   "description": "Synthetic orders", "table_count": 1, "is_active": True}]}
        if method == "POST" and (rest == "/chat" or re.match(r"^/sessions/[^/]+/messages$", rest)):
            if agent_id in self.limited:
                return 429, {"detail": "Query limit reached: 20 of 20 in the last 24 hours."}
            session_id = rest.split("/")[2] if rest.startswith("/sessions/") else body.get("session_id")
            if session_id:
                if self.sessions.get(session_id, {}).get("agent_id") != agent_id:
                    return 404, {"detail": f"Session {session_id} not found for agent {agent_id}"}
            else:
                session_id = str(uuid.uuid4())
                self.sessions[session_id] = {"agent_id": agent_id, "turns": []}
            return 200, self.answer(agent_id, session_id, body)
        session = re.match(r"^/sessions(?:/([^/]+))?$", rest)
        if method == "GET" and session:
            if not session.group(1):
                return 200, {"sessions": [{"session_id": sid, "session_title": "Regions",
                                           "display_message": s["turns"][0]["query"], "created_time": "2026-10-23T10:00:00"}
                                          for sid, s in self.sessions.items() if s["agent_id"] == agent_id]}
            stored = self.sessions.get(session.group(1))
            if not stored or stored["agent_id"] != agent_id:
                return 404, {"detail": f"Session {session.group(1)} not found for agent {agent_id}"}
            data = []
            for turn in stored["turns"]:
                data.append({"chat_id": turn["chat_id"], "role": "user", "message": turn["query"]})
                data.append({"chat_id": turn["chat_id"], "role": "assistant", "message": turn["answer"],
                             "user_feedback": None,
                             "debug_info": {"query": turn["query"], "sql_query": SQL,
                                            "db_output": json.dumps([[r["region"], r["total"]] for r in ROWS])},
                             "graph_output": turn["chart"], "result": turn["block"]})
            return 200, {"session_id": session.group(1), "session_title": "Regions",
                         "created_time": "2026-10-23T10:00:00", "conversation_data": data}
        return 404, {"detail": "Not Found"}

    def answer(self, agent_id, session_id, body):
        agent = AGENTS[agent_id]
        block = {"columns": [{"name": "region", "type": "text"}, {"name": "total", "type": "numeric"}],
                 "rows": ROWS, "row_count": 2, "truncated": False}
        chart = {"chart_suggestion": "bar", "chart_data": [{"label": r["region"], "value": float(r["total"])} for r in ROWS],
                 "metadata": {"x_axis": "region", "y_axis": "total"}}
        prior = len(self.sessions[session_id]["turns"])
        text = "North: 250.00, South: 200.00." if not prior else f"Follow-up {prior} answered with earlier context."
        chat_id = str(uuid.uuid4())
        self.sessions[session_id]["turns"].append({"chat_id": chat_id, "query": body["query"], "answer": text,
                                                   "chart": chart, "block": block})
        debug = {"query": body["query"], "refined_query": body["query"], "selected_db_id": "db-1",
                 "selected_db_name": "sample_sales"} if body.get("debug_info") else None
        if debug is not None and agent["show_sql_query"]:
            debug.update(sql_query=SQL, selected_tables=["orders"])
        if debug is not None and agent["show_db_result"]:
            debug["db_result"] = block
        with_chart = body.get("chart_output", True)
        return {"response": text, "session_id": session_id, "chat_id": chat_id, "follow_up": None,
                "is_answered": True, "trace_id": None, "debug_info": debug,
                "chart_output": chart if with_chart else None, "graph_output": chart if with_chart else None}


def serve(api: FakeApi):
    """Run the fake on a loopback port in a thread; returns (server, base_url)."""
    class Handler(BaseHTTPRequestHandler):
        def _reply(self):
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}") if length else {}
            status, payload = api.handle(self.command, self.path, self.headers.get("X-API-Key"), body)
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_GET = do_POST = _reply

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/nl2sql/api"
