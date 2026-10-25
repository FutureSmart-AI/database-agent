"""Request/response models for per-owner NL2SQL configuration.

Response shape mirrors fs-agent-usage-limits' owner config (`platform_limits`,
`enabled_services`) so the dashboard can switch base URL without reshaping its parsing —
but it carries only the fields NL2SQL can answer for itself. `platform_limits` therefore
has three keys, not seven, and `enabled_services` has one entry, not six. See
`models.sql_models.Nl2sqlOwnerConfig` for what is omitted and why.
"""
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class PlatformLimits(BaseModel):
    """The caps NL2SQL knows about. None = unlimited.

    Only `max_queries_per_day` is ENFORCED — chat returns 429 past it, counted over a
    rolling 24 hours per owner across all of their agents. The others are
    reported by `/usage/status` so the dashboard can show headroom, but nothing blocks on
    them.
    """
    max_agents: Optional[int] = Field(None, ge=0)
    max_team_members: Optional[int] = Field(None, ge=0)
    max_llm_tokens_per_month: Optional[int] = Field(None, ge=0)
    # Enforced — chat returns 429 past it. Counted over a rolling 24 hours.
    # 0 blocks every request; None means unlimited.
    max_queries_per_day: Optional[int] = Field(None, ge=0)


class OwnerConfigResponse(BaseModel):
    owner_id: str
    tier_type: str
    base_tier: Optional[str] = None
    platform_limits: PlatformLimits
    # Whose provider keys pay for this owner's model calls: "own" (bring-your-own-key; a
    # missing or invalid key is an error) or "platform". Always the EFFECTIVE value — the
    # deployment default when the owner has no stored choice.
    provider_key_source: Literal["own", "platform"] = "platform"
    # No "is this service enabled" field. The usage service has `enabled_services` because
    # it answers for six services, and the dashboard reads it from there. Here it could
    # only ever describe NL2SQL itself — and by the time a request reaches this service the
    # owner is demonstrably using it. Nothing enforced it either, so it was a field that
    # could only ever say "yes".
    #
    # True when the owner has no stored row and these are the defaults. Lets the UI show
    # "not configured" without a second call.
    is_default: bool = False


class OwnerConfigUpdate(BaseModel):
    """Body for PUT (full) and PATCH (partial).

    Every field optional. On PUT anything omitted returns to its default; on PATCH it is
    left alone.
    """
    tier_type: Optional[Literal["trial", "payg", "custom"]] = None
    base_tier: Optional[Literal["trial", "payg"]] = None
    platform_limits: Optional[PlatformLimits] = None
    # Master key only, like every write here: who pays for model calls is a commercial term.
    provider_key_source: Optional[Literal["own", "platform"]] = None

    model_config = ConfigDict(json_schema_extra={
        "example": {"tier_type": "payg",
                    "platform_limits": {"max_agents": 50, "max_llm_tokens_per_month": 5000000}}
    })


class CurrentUsage(BaseModel):
    """What the owner is using now, counted from NL2SQL's own tables."""
    agents: int
    tokens_this_month: int
    team_members: int
    # Chat turns in the ROLLING 24 hours ending now — every agent this owner has, plus
    # their CSV-agent turns, sharing one allowance. From nl2sql_logs, the canonical
    # per-turn record, not nl2sql_agent_health_events, which starts 2026-08-13 and would
    # under-count an established owner by orders of magnitude.
    queries_last_24h: int
    # When the owner next regains an allowance: 24h after the oldest turn still counted.
    # None when nothing is counted.
    queries_reset_at: Optional[str] = None
    month_start: str


class RemainingQuota(BaseModel):
    """Headroom per cap. None where the cap is unlimited."""
    agents: Optional[int] = None
    tokens_this_month: Optional[int] = None
    team_members: Optional[int] = None
    queries_last_24h: Optional[int] = None


class UsageStatusResponse(BaseModel):
    """Config + live usage + headroom, for the Usage & Limits screen.

    `exceeded` lists caps already over. Note this endpoint only REPORTS — nothing in
    NL2SQL blocks a request for being over a cap. Enforcement is a separate decision.
    """
    owner_id: str
    tier_type: str
    limits: PlatformLimits
    current_usage: CurrentUsage
    remaining: RemainingQuota
    exceeded: list[str] = Field(default_factory=list)
