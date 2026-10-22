"""The Limits tab: what a workspace is allowed to use, and how much of it has been used.

`owner_config_db_utils.get_current_usage` already answers the four caps that existed
before this screen. The Limits tab needs more than those four, and needs each one to carry
the words and the escape route that go beside it, so this module builds the whole tab in
one read rather than leaving the dashboard to assemble it from several.

Counted on read, never stored — the same choice as `get_current_usage`, and for the same
reason: a stored running total is a second thing to keep correct, and counting cannot
drift from the tables it counts.

THE ONE RULE WORTH READING TWICE. The token and cost ceilings count PLATFORM-key work
only. That is not a filter applied for tidiness — it is what makes "lifted by your own
key" true rather than decorative. Work the owner's own credential paid for is billed to
them by their provider, so a FutureSmart ceiling has nothing to say about it. Bring a key,
that provider's work stops counting, and the bar drops on its own.

The daily chat cap is lifted the same way, and this is not cosmetic either: enforcement in
`check_query_allowed` reads the SAME `owner_key_coverage.chat_cap_lifted` this module does,
so a row shown as lifted really does mean chat will not return 429. Coverage there means
every provider the owner's agents are configured to use — holding some is not enough,
because a turn split across their key and ours still costs us money.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import distinct, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from chatbot_management.db_utils.owner_config_db_utils import (
    count_queries_last_24h,
    get_owner_config,
)
from chatbot_management.db_utils.owner_key_coverage import get_key_coverage
from chatbot_management.db_utils.usage_event_retrieval import PLATFORM_KEY
from chatbot_management.utils.usage_limits import (
    LIMIT_WINDOW_DAYS,
    MAX_DATABASES,
    MAX_DATABASES_PER_AGENT,
    TOKEN_RATE_USD,
    cost_ceiling,
    estimated_cost,
    tier_label,
)
from logger import logger
from models.sql_models import (
    ChatbotConnection,
    ChatbotDetails,
    UsageEvent,
    UsageMetricRow,
)
from otel_tracing import track_time

# The metadata key each event records its provider under. Only LLM and embedding work has
# one; database and code-execution events have no provider at all.
_PROVIDER = UsageEvent.event_metadata["provider"].astext

# Platform-key work, with an absent key_type reading as platform — the same rule the Usage
# screen's consumption-source filter uses. See `_DERIVED_DIMENSIONS` in
# usage_event_retrieval: writers that omit key_type accounted for 18.7% of tokens over a
# 30-day window, and leaving them out of the ceiling would under-report every workspace.
_IS_PLATFORM = func.coalesce(UsageEvent.key_type, PLATFORM_KEY) == PLATFORM_KEY


async def _count_agents(session: AsyncSession, owner_id: str) -> int:
    return int((await session.execute(
        select(func.count()).select_from(ChatbotDetails).where(
            ChatbotDetails.owner_id == owner_id,
            ChatbotDetails.deleted == False,  # noqa: E712
        )
    )).scalar_one() or 0)


async def _count_databases(session: AsyncSession, owner_id: str):
    """(total across every agent, most on any single agent).

    A database switched off in Settings still counts — `is_active` is not filtered, only
    `deleted`. Detaching a database is what frees the allowance; pausing it is not.
    """
    rows = (await session.execute(
        select(ChatbotConnection.agent_id, func.count())
        .where(
            ChatbotConnection.owner_id == owner_id,
            ChatbotConnection.deleted == False,  # noqa: E712
        )
        .group_by(ChatbotConnection.agent_id)
    )).all()
    total = sum(int(r[1] or 0) for r in rows)
    largest = max((int(r[1] or 0) for r in rows), default=0)
    return total, largest


async def _platform_window(session: AsyncSession, owner_id: str, window_start: datetime):
    """(tokens, providers) served on PLATFORM keys inside the billing window."""
    tokens = (await session.execute(
        select(func.coalesce(func.sum(UsageMetricRow.metric_value), 0))
        .select_from(UsageEvent)
        .join(UsageMetricRow, UsageMetricRow.event_id == UsageEvent.event_id)
        .where(
            UsageEvent.owner_id == owner_id,
            UsageEvent.timestamp >= window_start,
            UsageMetricRow.metric_name == "total_tokens",
            _IS_PLATFORM,
        )
    )).scalar_one()

    rows = (await session.execute(
        select(distinct(_PROVIDER)).where(
            UsageEvent.owner_id == owner_id,
            UsageEvent.timestamp >= window_start,
            _PROVIDER.isnot(None),
            _IS_PLATFORM,
        )
    )).all()
    providers = sorted({str(r[0]).lower() for r in rows if r[0]})
    return float(tokens or 0), providers


def _item(key: str, label: str, used, limit, unit: str, maximum: str, note: str,
          lifted_by: Optional[List[str]] = None, held: Optional[List[str]] = None,
          enforced: bool = False) -> Dict[str, Any]:
    """One limit row, with its progress and its escape route already resolved.

    `percent` is computed here rather than left to the caller so the bar and the
    "x of y" text can never be derived from different numbers. It is None whenever there
    is no ceiling to be a percentage of — unlimited, or lifted.
    """
    lifted_by = sorted(lifted_by or [])
    held = held or []
    missing = [p for p in lifted_by if p not in held]
    # Lifted only if there is something to lift it and the owner holds all of it. An
    # empty `lifted_by` means no key removes this cap, so it can never read as lifted.
    lifted = bool(lifted_by) and not missing

    percent = None
    if not lifted and limit:
        percent = min(100.0, (float(used) / float(limit)) * 100.0)
    elif not lifted and limit == 0:
        # A cap of 0 blocks everything; it is full by definition, not 0% used.
        percent = 100.0

    return {
        "key": key,
        "label": label,
        "used": used,
        "limit": limit,
        "unit": unit,
        # The ceiling is stated as words even when lifted: "lifted" must not mean the
        # reader loses sight of what the platform cap actually is.
        "maximum": maximum,
        "note": note,
        "lifted_by": lifted_by,
        "held": [p for p in lifted_by if p in held],
        "missing": missing,
        "lifted": lifted,
        "percent": percent,
        # What moves this one. Both routes are offered on any cap a key can lift.
        "raises": "plan-or-own-keys" if lifted_by else "plan",
        "enforced": enforced,
    }


@track_time("DB: Owner Limits")
async def get_owner_limits(session: AsyncSession, owner_id: str) -> Dict[str, Any]:
    """The whole Limits tab for one owner: tier, window, and every limit with its usage."""
    config = await get_owner_config(session, owner_id)
    limits = config.get("platform_limits") or {}

    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=LIMIT_WINDOW_DAYS)

    agents = await _count_agents(session, owner_id)
    db_total, db_largest = await _count_databases(session, owner_id)
    # Held providers come from the coverage helper rather than a second query of the same
    # table, so this tab and the 429 decision are reading one answer.
    coverage = await get_key_coverage(session, owner_id)
    held = coverage["held"]
    queries, queries_reset_at = await count_queries_last_24h(session, owner_id)
    tokens, platform_providers = await _platform_window(session, owner_id, window_start)

    cost = estimated_cost(tokens)
    token_ceiling = limits.get("max_llm_tokens_per_month")
    ceiling = cost_ceiling(token_ceiling, tokens, cost)
    tier = tier_label(config.get("tier_type"))

    # Credentials are one per provider per owner, so the ceiling IS the number of
    # providers this product supports. Derived from that list rather than written down,
    # so adding a provider cannot leave a stale literal behind.
    from api.v1.routers.credentials import _LLM_PROVIDERS
    provider_count = len(_LLM_PROVIDERS)

    groups = [
        {
            "group": "Workspace",
            "items": [
                _item(
                    "agents", "Agents you can create", agents,
                    limits.get("max_agents"), "agents",
                    f"{limits.get('max_agents')} agents on {tier}",
                    "Every database agent in this workspace counts, active or paused.",
                ),
                _item(
                    "databases", "Connected databases", db_total,
                    MAX_DATABASES, "databases",
                    f"{MAX_DATABASES} databases across every agent",
                    "Counted across every agent. A database switched off in Settings "
                    "still counts; detaching it is what frees the allowance. This cap is "
                    "the same for every workspace and cannot yet be raised per owner.",
                ),
                _item(
                    "databases_per_agent", "Databases on a single agent", db_largest,
                    MAX_DATABASES_PER_AGENT, "databases",
                    "No limit on how many databases one agent routes between",
                    "Your largest agent right now. Nothing caps this — it is here so you "
                    "can see the number, not because it is running out.",
                ),
                _item(
                    "credentials", "Credentials configured", len(held),
                    provider_count, "keys",
                    f"{provider_count} keys — one per provider this product supports",
                    "One key per provider. Adding a key here moves the token and cost "
                    "limits below, not this one.",
                ),
            ],
        },
        {
            "group": "Requests, tokens and cost",
            "items": [
                _item(
                    "queries_per_day", "Chat requests per day", queries,
                    limits.get("max_queries_per_day"), "requests",
                    f"{limits.get('max_queries_per_day')} requests per rolling 24 hours",
                    "Questions asked across every agent and the CSV agent, sharing one "
                    "allowance. The window rolls rather than resetting: the allowance "
                    "returns a question at a time as turns age past 24 hours."
                    + (f" Next one back at {queries_reset_at}." if queries_reset_at else ""),
                    # Genuinely liftable: enforcement reads the same coverage, so a lifted
                    # row means chat will not 429. All required providers, not any one of
                    # them — a turn split across their key and ours still costs us.
                    lifted_by=coverage["required"], held=held, enforced=True,
                ),
                _item(
                    "tokens", "Total tokens this billing period", int(tokens),
                    token_ceiling, "tokens",
                    f"{token_ceiling} tokens per billing period on {tier}"
                    if token_ceiling is not None else "No token ceiling on " + tier,
                    "Input plus output across every model that served a request on "
                    "FutureSmart platform keys. Work your own keys paid for is not "
                    "counted here.",
                    lifted_by=platform_providers, held=held,
                ),
                # NOT rounded. The cost bar and the token bar describe the same
                # consumption and must read the same percentage; because the ceiling is
                # blended_rate * token_ceiling and spend is blended_rate * tokens, they
                # are equal by construction — and rounding either one here breaks that.
                # Rounding to 4dp was tried and measurably did break it: 0.7819% against
                # 0.7816% for one production owner. Format for display in the client.
                _item(
                    "cost", "Estimated cost this billing period", cost,
                    ceiling, "USD",
                    f"${ceiling:.4f} per billing period — derived from the token ceiling "
                    f"at this workspace's own blended rate"
                    if ceiling is not None else "No cost ceiling on " + tier,
                    f"An estimate priced at ${TOKEN_RATE_USD} per token, not a bill. Work "
                    "paid for by your own provider keys is billed to you by that "
                    "provider, not by us.",
                    lifted_by=platform_providers, held=held,
                ),
            ],
        },
    ]

    exceeded = [
        it["key"]
        for g in groups for it in g["items"]
        if not it["lifted"] and it["limit"] is not None and it["used"] >= it["limit"]
    ]

    logger.info(
        f"Owner limits | owner_id={owner_id} agents={agents} dbs={db_total} "
        f"queries_24h={queries} platform_tokens={int(tokens)} exceeded={exceeded}"
    )

    return {
        "owner_id": owner_id,
        "tier": {
            "name": tier,
            "tier_type": config.get("tier_type"),
            "is_default": bool(config.get("is_default")),
        },
        "billing_window": {
            "days": LIMIT_WINDOW_DAYS,
            "start": window_start.isoformat(),
            "end": now.isoformat(),
        },
        "own_credentials": held,
        "token_rate_usd": TOKEN_RATE_USD,
        "groups": groups,
        "exceeded": exceeded,
    }
