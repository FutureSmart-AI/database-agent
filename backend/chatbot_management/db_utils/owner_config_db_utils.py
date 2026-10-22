"""Per-owner NL2SQL configuration: read, upsert, and the live counts behind the caps.

Ported in spirit from fs-agent-usage-limits' `utils/owner_config_management.py`, reduced
to the fields NL2SQL can answer for itself (see `models.sql_models.Nl2sqlOwnerConfig`).

Two things worth knowing:

* **Reads never 404.** An owner with no row gets the defaults from
  `chatbot_management/utils/owner_defaults.py`, flagged `is_default: true`. A customer who
  has never been configured is usable immediately, and the dashboard needs no special case.

* **`current_usage` is counted here, not stored.** Agents come from `chatbot_details`,
  tokens from `nl2sql_agent_health_events`, team members from `chatbot_invitations` — all
  local. Storing running totals would mean a second thing to keep correct; counting on
  read cannot drift.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from chatbot_management.utils.owner_defaults import DEFAULT_LIMITS, default_config
from logger import logger
from models.sql_models import (
    AgentHealthEvent,
    ChatbotDetails,
    ChatbotInvitations,
    ChatLogs,
    Nl2sqlOwnerConfig,
    UsageEvent,
)
from otel_tracing import track_time

# Caps a caller may set. Anything else is rejected rather than silently ignored.
SETTABLE_LIMITS = ("max_agents", "max_team_members", "max_llm_tokens_per_month",
                   "max_queries_per_day")
VALID_TIERS = ("trial", "payg", "custom")


def _to_response(row: Nl2sqlOwnerConfig) -> Dict[str, Any]:
    """Shape a stored row for the API.

    Mirrors the usage service's config response minus `enabled_services` — see the note on
    `OwnerConfigResponse` for why that field is not carried over.

    The `nl2sql_enabled` / `nl2sql_enabled_at` COLUMNS still exist on the table, unused and
    defaulted. They are left in place rather than dropped in a follow-up migration, so
    that per-owner gating can be added later without another schema change. Nothing reads
    them today.
    """
    return {
        "owner_id": row.owner_id,
        "tier_type": row.tier_type,
        "base_tier": row.base_tier,
        "platform_limits": {
            "max_agents": row.max_agents,
            "max_team_members": row.max_team_members,
            "max_llm_tokens_per_month": row.max_llm_tokens_per_month,
            "max_queries_per_day": row.max_queries_per_day,
        },
        "is_default": False,
    }


@track_time("DB: Get Owner Config")
async def get_owner_config(session: AsyncSession, owner_id: str) -> Dict[str, Any]:
    """This owner's NL2SQL configuration, or the defaults when they have no row."""
    result = await session.execute(
        select(Nl2sqlOwnerConfig).where(Nl2sqlOwnerConfig.owner_id == owner_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return default_config(owner_id)
    return _to_response(row)


@track_time("DB: Upsert Owner Config")
async def upsert_owner_config(
    session: AsyncSession,
    owner_id: str,
    *,
    tier_type: Optional[str] = None,
    base_tier: Optional[str] = None,
    limits: Optional[Dict[str, Optional[int]]] = None,
    acting_user: Optional[str] = None,
    replace: bool = False,
) -> Dict[str, Any]:
    """Create or update an owner's configuration.

    `replace=True` (PUT) starts from the defaults, so any field the caller omits returns
    to its default rather than keeping a value they did not send. `replace=False` (PATCH)
    changes only what is provided. Doing PUT any other way would make a partial payload
    silently preserve stale caps.
    """
    result = await session.execute(
        select(Nl2sqlOwnerConfig).where(Nl2sqlOwnerConfig.owner_id == owner_id)
    )
    row = result.scalar_one_or_none()
    now = datetime.utcnow()

    if row is None:
        defaults = default_config(owner_id)
        row = Nl2sqlOwnerConfig(
            owner_id=owner_id,
            tier_type=defaults["tier_type"],
            base_tier=defaults["base_tier"],
            **defaults["platform_limits"],
        )
        session.add(row)
    elif replace:
        defaults = default_config(owner_id)
        row.tier_type = defaults["tier_type"]
        row.base_tier = defaults["base_tier"]
        for k, v in defaults["platform_limits"].items():
            setattr(row, k, v)

    if tier_type is not None:
        row.tier_type = tier_type
    if base_tier is not None:
        row.base_tier = base_tier
    if limits:
        for k, v in limits.items():
            if k in SETTABLE_LIMITS:
                setattr(row, k, v)
    row.updated_at = now
    row.updated_by = acting_user
    await session.commit()
    await session.refresh(row)
    logger.info(f"Owner config saved | owner_id={owner_id} by={acting_user}")
    return _to_response(row)


@track_time("DB: Owner Current Usage")
async def get_current_usage(session: AsyncSession, owner_id: str) -> Dict[str, Any]:
    """What this owner is actually using right now, counted from NL2SQL's own tables.

    Only the three things the caps cover. `tokens_this_month` is a calendar-month total
    from the health events, which is what the token cap is expressed against.
    """
    agents = (await session.execute(
        select(func.count()).select_from(ChatbotDetails).where(
            ChatbotDetails.owner_id == owner_id,
            ChatbotDetails.deleted == False,  # noqa: E712
        )
    )).scalar_one()

    month_start = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0, tzinfo=None
    )
    tokens = (await session.execute(
        select(func.coalesce(func.sum(AgentHealthEvent.total_tokens), 0)).where(
            AgentHealthEvent.owner_id == owner_id,
            AgentHealthEvent.event_ts >= month_start,
        )
    )).scalar_one()

    # Distinct invited addresses across this owner's agents — a person invited to three
    # agents is one team member, not three.
    members = (await session.execute(
        select(func.count(func.distinct(ChatbotInvitations.invited_user_email)))
        .select_from(ChatbotInvitations)
        .join(ChatbotDetails, ChatbotDetails.agent_id == ChatbotInvitations.agent_id)
        .where(ChatbotDetails.owner_id == owner_id)
    )).scalar_one()

    queries, reset_at = await count_queries_last_24h(session, owner_id)

    return {
        "agents": int(agents or 0),
        "tokens_this_month": int(tokens or 0),
        "team_members": int(members or 0),
        "queries_last_24h": queries,
        "queries_reset_at": reset_at,
        "month_start": month_start.isoformat() + "Z",
    }


@track_time("DB: Owner Queries Last 24h")
async def count_queries_last_24h(session: AsyncSession, owner_id: str):
    """Chat turns for this owner in the rolling 24 hours ending now.

    Returns `(count, reset_at)`, where `reset_at` is when the OLDEST still-counted turn
    ages out — the moment the owner regains one query. None when nothing is counted.

    A ROLLING window, not a calendar day: the allowance comes back on its own as turns age
    past 24 hours, so nothing has to reset it and there is no midnight cliff where a whole
    allowance reappears at once.

    OWNER-WIDE, NOT PER AGENT. Turns are counted across every agent the owner has, so ten
    agents share one allowance of 20 rather than getting 20 each.

    Two sources, because two surfaces answer questions:

      nl2sql_logs   one row per agent chat turn, joined to chatbot_details for ownership.
                    The canonical per-turn record, covering full history — NOT
                    nl2sql_agent_health_events, which starts 2026-08-13 and reported 16
                    turns for an owner who had actually asked 2,403.

      usage_events  one `csv_api_request` row per CSV-agent turn. That endpoint has no
                    agent, so it leaves no nl2sql_logs row, but it is an NL2SQL chat and
                    shares the allowance.
    """
    window_start = datetime.utcnow() - timedelta(hours=24)

    agent_turns = (await session.execute(
        select(func.count(), func.min(ChatLogs.created_at))
        .select_from(ChatLogs)
        .join(ChatbotDetails, ChatbotDetails.agent_id == ChatLogs.agent_id)
        .where(
            ChatbotDetails.owner_id == owner_id,
            ChatbotDetails.deleted == False,  # noqa: E712
            ChatLogs.created_at >= window_start,
        )
    )).one()

    csv_turns = (await session.execute(
        select(func.count(), func.min(UsageEvent.timestamp)).where(
            UsageEvent.owner_id == owner_id,
            UsageEvent.operation == "csv_api_request",
            UsageEvent.timestamp >= window_start,
        )
    )).one()

    total = int(agent_turns[0] or 0) + int(csv_turns[0] or 0)

    # The oldest turn still inside the window is what sets when the allowance next moves.
    oldest = [t for t in (agent_turns[1], csv_turns[1]) if t is not None]
    reset_at = None
    if oldest:
        first = min(oldest)
        if first.tzinfo is not None:
            first = first.astimezone(timezone.utc).replace(tzinfo=None)
        reset_at = (first + timedelta(hours=24)).isoformat() + "Z"

    return total, reset_at


@track_time("DB: Check Owner Query Cap")
async def check_query_allowed(session: AsyncSession, owner_id: str) -> Optional[dict]:
    """Whether this owner may ask another question. None when allowed.

    The cap is per OWNER over a rolling 24 hours, shared across all of their agents and
    the CSV agent — ten agents do not get ten allowances. An owner with no configuration
    row gets the default, so the cap is not something an owner escapes by never having
    been configured.

    LIFTED BY THE OWNER'S OWN KEYS. The cap exists because chat runs on FutureSmart
    platform credentials, so an owner whose own keys cover every provider their agents use
    is paying their provider directly and is not capped. Coverage is decided by
    `owner_key_coverage.chat_cap_lifted`, the same function the Limits tab reads, so the
    screen and the 429 can never disagree about whether the cap applies.

    Returns a dict describing the breach when they may not, so the caller can put real
    numbers in the error rather than a bare refusal.

    FAILS OPEN. If the cap or the count cannot be read, the question is allowed and the
    failure is logged as an error. Refusing a paying customer because of a database hiccup
    is worse than letting a few extra queries through, and this check sits in front of
    every chat request.
    """
    try:
        result = await session.execute(
            select(Nl2sqlOwnerConfig.max_queries_per_day).where(
                Nl2sqlOwnerConfig.owner_id == owner_id
            )
        )
        row = result.one_or_none()
        if row is None:
            # No configuration row at all: the default applies, so a brand-new owner is
            # capped from their first question rather than being unlimited until someone
            # happens to save a row for them.
            cap = DEFAULT_LIMITS.get("max_queries_per_day")
        else:
            cap = row[0]
        if cap is None:
            # An explicit NULL means unlimited.
            return None

        # Only the turn count is needed, so this deliberately does not call
        # get_current_usage — counting agents, tokens and team members on every chat
        # request would add three queries to the hot path for numbers nothing here reads.
        used, reset_at = await count_queries_last_24h(session, owner_id)
        if used < cap:
            return None

        # Coverage is only worth reading HERE, on the path that would otherwise refuse.
        # An owner under the cap is allowed whichever keys they hold, so checking every
        # request would add queries to the hot path to change nothing. Deciding it late
        # also means adding a key takes effect on the very next request.
        from chatbot_management.db_utils.owner_key_coverage import chat_cap_lifted

        if await chat_cap_lifted(session, owner_id):
            logger.info(
                f"Query cap lifted by own credentials | owner_id={owner_id} used={used} "
                f"cap={cap}"
            )
            return None

        logger.warning(
            f"Query cap reached | owner_id={owner_id} used={used} cap={cap} "
            f"resets_at={reset_at}"
        )
        return {"used": used, "cap": cap, "resets_at": reset_at}

    except Exception as e:
        logger.error(
            f"check_query_allowed: could not evaluate the cap for {owner_id}, allowing "
            f"the request: {e}"
        )
        return None
