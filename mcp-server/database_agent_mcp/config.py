"""Environment configuration for the Database Agent MCP server.

The server holds no product logic and no database credentials. It only needs the product
API root and one or more existing Database Agent API credentials:

* ``DATABASE_AGENT_AGENT_KEYS`` — per-agent keys issued by ``POST /v1/agents/{id}/api-keys``,
  written as ``AGENT_ID=KEY`` pairs separated by commas or newlines. Recommended: each key
  only works on its own agent and cannot administer it.
* ``DATABASE_AGENT_API_KEY`` — the operator (master) key. Reaches every agent; use it only
  for a trusted single-operator installation.

Secrets are never included in ``repr``, logs or error messages.
"""
from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional, Tuple
from urllib.parse import urlsplit

DEFAULT_API_URL = "http://127.0.0.1:18000/nl2sql/api"
DEFAULT_TIMEOUT_SECONDS = 180.0


class ConfigError(ValueError):
    """Invalid or missing configuration. Messages never contain secret values."""


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def parse_agent_keys(raw: str) -> Dict[str, str]:
    keys: Dict[str, str] = {}
    for position, item in enumerate(raw.replace("\n", ",").split(","), start=1):
        item = item.strip()
        if not item:
            continue
        agent_id, sep, key = item.partition("=")
        agent_id, key = agent_id.strip(), key.strip()
        if not sep or not agent_id or not key:
            raise ConfigError(
                f"DATABASE_AGENT_AGENT_KEYS entry {position} is not AGENT_ID=KEY"
            )
        if agent_id in keys:
            raise ConfigError(f"DATABASE_AGENT_AGENT_KEYS lists agent {agent_id} twice")
        keys[agent_id] = key
    return keys


@dataclass(frozen=True)
class Settings:
    api_url: str = DEFAULT_API_URL
    operator_key: Optional[str] = field(default=None, repr=False)
    agent_keys: Dict[str, str] = field(default_factory=dict, repr=False)
    timeout: float = DEFAULT_TIMEOUT_SECONDS

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> "Settings":
        api_url = (env.get("DATABASE_AGENT_URL") or DEFAULT_API_URL).strip().rstrip("/")
        parts = urlsplit(api_url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ConfigError("DATABASE_AGENT_URL must be an http(s) URL such as " + DEFAULT_API_URL)
        insecure_ok = (env.get("DATABASE_AGENT_ALLOW_INSECURE_HTTP") or "").strip().lower() in ("1", "true", "yes")
        if parts.scheme == "http" and not _is_loopback(parts.hostname) and not insecure_ok:
            raise ConfigError(
                "DATABASE_AGENT_URL uses plain HTTP to a non-loopback host, which would send API keys "
                "unencrypted. Use HTTPS, or set DATABASE_AGENT_ALLOW_INSECURE_HTTP=1 for a private network."
            )

        operator_key = (env.get("DATABASE_AGENT_API_KEY") or "").strip() or None
        agent_keys = parse_agent_keys(env.get("DATABASE_AGENT_AGENT_KEYS") or "")
        if not operator_key and not agent_keys:
            raise ConfigError(
                "No Database Agent credential configured. Set DATABASE_AGENT_AGENT_KEYS "
                "(AGENT_ID=KEY pairs, recommended) or DATABASE_AGENT_API_KEY (operator key)."
            )

        raw_timeout = (env.get("DATABASE_AGENT_TIMEOUT_SECONDS") or "").strip()
        try:
            timeout = float(raw_timeout) if raw_timeout else DEFAULT_TIMEOUT_SECONDS
        except ValueError:
            raise ConfigError("DATABASE_AGENT_TIMEOUT_SECONDS must be a number") from None
        if timeout <= 0:
            raise ConfigError("DATABASE_AGENT_TIMEOUT_SECONDS must be positive")
        return cls(api_url=api_url, operator_key=operator_key, agent_keys=agent_keys, timeout=timeout)

    def credential_for(self, agent_id: Optional[str]) -> Tuple[str, str]:
        """Return ``(key, kind)`` for a request. A per-agent key wins over the operator key."""
        if agent_id and agent_id in self.agent_keys:
            return self.agent_keys[agent_id], "agent_key"
        if self.operator_key:
            return self.operator_key, "operator_key"
        if agent_id:
            raise ConfigError(
                f"No credential configured for agent {agent_id}. Add it to DATABASE_AGENT_AGENT_KEYS "
                "or call list_agents to see the agents this server can reach."
            )
        raise ConfigError("This operation needs DATABASE_AGENT_API_KEY (operator key)")
