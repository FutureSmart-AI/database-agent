"""Thin async client for the existing Database Agent REST API.

Every product decision — authentication, agent-key scope, query caps, model configuration,
table visibility, SQL access policy and execution — stays in the API. This module only sends
the same requests the UI and direct API clients send.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx

from .config import Settings


class ApiError(Exception):
    """A non-success API response, carrying the server's own (non-secret) detail."""

    def __init__(self, status: int, detail: str, code: Optional[str] = None):
        super().__init__(f"HTTP {status}: {detail}")
        self.status = status
        self.detail = detail
        self.code = code


def _detail(response: httpx.Response) -> tuple[str, Optional[str]]:
    try:
        body = response.json()
    except ValueError:
        return (response.text or response.reason_phrase or "")[:500], None
    detail = body.get("detail", body) if isinstance(body, dict) else body
    if isinstance(detail, dict):
        return str(detail.get("message") or detail)[:500], detail.get("code")
    return str(detail)[:500], None


def _seg(value: str) -> str:
    return quote(str(value), safe="")


class DatabaseAgentApi:
    def __init__(self, settings: Settings, transport: Optional[httpx.AsyncBaseTransport] = None):
        self.settings = settings
        self._http = httpx.AsyncClient(
            base_url=settings.api_url + "/",
            timeout=httpx.Timeout(settings.timeout, connect=10.0),
            transport=transport,
            headers={"Accept": "application/json", "User-Agent": "database-agent-mcp"},
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _request(self, method: str, path: str, *, agent_id: Optional[str] = None,
                       json: Optional[dict] = None, params: Optional[dict] = None) -> Any:
        key, _ = self.settings.credential_for(agent_id)
        response = await self._http.request(method, path, json=json, params=params,
                                            headers={"X-API-Key": key})
        if response.status_code >= 400:
            detail, code = _detail(response)
            raise ApiError(response.status_code, detail, code)
        return response.json()

    async def list_all_agents(self) -> List[Dict[str, Any]]:
        """Operator key only: every agent, across pages."""
        agents: List[Dict[str, Any]] = []
        page = 1
        while True:
            body = await self._request("GET", "v1/agents", params={"page": page, "limit": 100})
            agents += (body.get("owned_agents") or []) + (body.get("invited_agents") or [])
            if page >= int((body.get("pagination") or {}).get("pages") or 1):
                return agents
            page += 1

    async def get_agent(self, agent_id: str) -> Dict[str, Any]:
        return (await self._request("GET", f"v1/agents/{_seg(agent_id)}", agent_id=agent_id))["data"]

    async def list_databases(self, agent_id: str) -> List[Dict[str, Any]]:
        body = await self._request("GET", f"v1/agents/{_seg(agent_id)}/databases", agent_id=agent_id)
        return body.get("data") or []

    async def ask(self, agent_id: str, question: str, session_id: Optional[str] = None,
                  chart_output: Optional[bool] = None) -> Dict[str, Any]:
        # debug_info=True asks for the SQL/rows block; the agent's own show_sql_query and
        # show_db_result settings still decide, server-side, what that block may contain.
        body: Dict[str, Any] = {"query": question, "debug_info": True}
        if chart_output is not None:
            body["chart_output"] = chart_output
        if session_id:
            path = f"v1/agents/{_seg(agent_id)}/sessions/{_seg(session_id)}/messages"
        else:
            path = f"v1/agents/{_seg(agent_id)}/chat"
        return await self._request("POST", path, agent_id=agent_id, json=body, params={"stream": "false"})

    async def list_sessions(self, agent_id: str) -> List[Dict[str, Any]]:
        body = await self._request("GET", f"v1/agents/{_seg(agent_id)}/sessions", agent_id=agent_id)
        return body.get("sessions") or []

    async def get_session(self, agent_id: str, session_id: str) -> Dict[str, Any]:
        return await self._request("GET", f"v1/agents/{_seg(agent_id)}/sessions/{_seg(session_id)}",
                                   agent_id=agent_id)
