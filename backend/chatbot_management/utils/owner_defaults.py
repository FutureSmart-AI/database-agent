"""Default NL2SQL settings for an owner with no configuration row.

The API must always answer: an owner who has never been configured gets these rather
than a 404, so a brand-new customer is usable immediately and the dashboard never has to
special-case "no config yet".

Values match fs-agent-usage-limits' `config/owner_defaults.yaml` so a customer sees the
same numbers whichever service they ask — but only the fields NL2SQL can enforce are
here. See the note on `models.sql_models.Nl2sqlOwnerConfig` for what is deliberately
absent and why.

A cap of None means unlimited.

⚠ These are NL2SQL's own caps. If the platform's plan limits change in the usage service,
nothing updates them here — they are a copy, not a mirror. That is the trade-off of each
service owning its limits: a customer on "10 agents" gets 10 in NL2SQL and 10 in every
other service that does the same. If the caps must stay platform-wide, this file should be
replaced by a periodic sync from the usage service's owner config.
"""
from typing import Any, Dict, Optional

DEFAULT_TIER = "trial"
DEFAULT_BASE_TIER: Optional[str] = None

# Only the caps NL2SQL can count from its own database.
DEFAULT_LIMITS: Dict[str, Optional[int]] = {
    "max_agents": 10,
    "max_team_members": 5,
    "max_llm_tokens_per_month": 1_000_000,
    # ENFORCED — chat returns 429 past this, unlike the caps above which are only
    # reported. Applies to EVERY owner, including one with no stored row, so the cap is not
    # something an owner escapes by never having been configured.
    #
    # 20 per ROLLING 24 hours, per owner, shared across all of their agents and the CSV
    # agent — ten agents do not get ten allowances. Rolling rather than per calendar day so
    # the allowance returns as turns age out, with no reset job and no midnight cliff.
    #
    # Raise or remove it for one owner with
    # PATCH /v1/owners/{owner_id}/config {"platform_limits": {"max_queries_per_day": N}}
    # (null = unlimited).
    "max_queries_per_day": 20,
}

def default_config(owner_id: str) -> Dict[str, Any]:
    """The response body for an owner with no stored configuration."""
    from agent.utils.provider_key_scope import deployment_default_source
    return {
        "owner_id": owner_id,
        "tier_type": DEFAULT_TIER,
        "base_tier": DEFAULT_BASE_TIER,
        "platform_limits": dict(DEFAULT_LIMITS),
        # Not a constant here: the deployment chooses (DEFAULT_PROVIDER_KEY_SOURCE).
        "provider_key_source": deployment_default_source(),
        "is_default": True,
    }
