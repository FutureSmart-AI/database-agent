"""Whether an owner's own credentials cover the providers their chat actually uses.

The daily chat cap exists because chat runs on FutureSmart platform credentials. An owner
who brings their own key is paying their provider directly, so the cap has nothing left to
protect and is lifted for them.

WHY THIS IS ITS OWN MODULE. Two callers must agree exactly:

    check_query_allowed   decides whether chat returns 429
    get_owner_limits      tells the reader whether the cap applies to them

If they disagree, the Limits tab says "lifted by your own key" while chat still refuses —
or promises a cap that never fires. One function, both callers, so they cannot drift.

WHAT "COVERED" MEANS. Every LLM node a chat turn can touch, resolved per agent: the
provider on that agent's `chatbot_node_config` row, or the node's default when it has no
row. The owner must hold a key for ALL of them. Holding some is not enough — a turn that
runs four nodes on the customer's key and two on ours still costs us money, which is the
whole reason the cap exists.

With the shipped defaults that means three keys (openai, google, groq), because the
default nodes are spread across three providers. `missing` names the ones still needed, so
the Limits tab can tell the owner exactly what to add rather than leaving them to guess.
"""
from typing import Any, Dict, List

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from agent.utils.owner_credential_utils import canonical_provider
from logger import logger
from models.sql_models import ChatbotDetails, ChatbotNodeConfig, UserProviderKeys
from otel_tracing import track_time

# The LLM nodes a chat turn can touch, with the provider each falls back to when the agent
# has no override row. Mirrors VALID_NODE_NAMES / NODE_CONFIG_MAP in
# api/v1/utils/config_helper.py; imported from there rather than copied so a new node or a
# changed default cannot leave a stale duplicate here.
#
# `db_router` (multi-database agents only) and `chart_agent` (only when the question wants
# a chart) do not run on every turn, but they are still included: a node that CAN run on a
# platform key is a cost we can still incur, so it counts toward coverage.
def _node_defaults() -> Dict[str, str]:
    from api.v1.utils.config_helper import NODE_CONFIG_MAP, VALID_NODE_NAMES

    out = {}
    for node in VALID_NODE_NAMES:
        conf = NODE_CONFIG_MAP.get(node) or {}
        prov = conf.get("default_provider")
        if prov:
            out[node] = canonical_provider(prov)
    return out


async def _required_providers(session: AsyncSession, owner_id: str) -> List[str]:
    """Providers this owner's agents are configured to use, canonicalised."""
    defaults = _node_defaults()

    agent_ids = [r[0] for r in (await session.execute(
        select(ChatbotDetails.agent_id).where(
            ChatbotDetails.owner_id == owner_id,
            ChatbotDetails.deleted == False,  # noqa: E712
        )
    )).all() if r[0]]

    # No agents yet: the defaults are what their first agent will use, so coverage is
    # measured against those rather than reading as trivially complete.
    if not agent_ids:
        return sorted(set(defaults.values()))

    overrides = {}
    rows = (await session.execute(
        select(ChatbotNodeConfig.agent_id, ChatbotNodeConfig.node_name,
               ChatbotNodeConfig.provider)
        .where(
            ChatbotNodeConfig.agent_id.in_(agent_ids),
            ChatbotNodeConfig.deleted_at.is_(None),
            ChatbotNodeConfig.provider.isnot(None),
        )
    )).all()
    for agent_id, node_name, provider in rows:
        overrides[(agent_id, node_name)] = canonical_provider(provider)

    required = set()
    for agent_id in agent_ids:
        for node, default_provider in defaults.items():
            required.add(overrides.get((agent_id, node), default_provider))
    return sorted(p for p in required if p)


async def _held_providers(session: AsyncSession, owner_id: str) -> List[str]:
    """Providers this owner has stored a key for, canonicalised."""
    rows = (await session.execute(
        select(func.distinct(UserProviderKeys.provider)).where(
            UserProviderKeys.owner_id == owner_id
        )
    )).all()
    return sorted({canonical_provider(r[0]) for r in rows if r[0]})


@track_time("DB: Owner Key Coverage")
async def get_key_coverage(session: AsyncSession, owner_id: str) -> Dict[str, Any]:
    """Does this owner's own keys cover every provider their chat can use?

    Returns `{required, held, missing, covered}`. `covered` is True only when `required` is
    non-empty and nothing is missing — so an owner with no requirement to cover is never
    reported as having lifted anything.
    """
    required = await _required_providers(session, owner_id)
    held = await _held_providers(session, owner_id)
    missing = [p for p in required if p not in held]
    return {
        "required": required,
        "held": held,
        "missing": missing,
        "covered": bool(required) and not missing,
    }


async def chat_cap_lifted(session: AsyncSession, owner_id: str) -> bool:
    """Whether the daily chat cap is lifted for this owner by their own credentials.

    FAILS CLOSED, unlike the cap check that calls it. If coverage cannot be read we keep
    the cap: wrongly lifting it leaves spend uncapped until someone notices, while wrongly
    keeping it is visible to the customer immediately and recovers by itself.
    """
    try:
        return (await get_key_coverage(session, owner_id))["covered"]
    except Exception as e:
        logger.error(
            f"chat_cap_lifted: could not read key coverage for {owner_id}, keeping the "
            f"cap: {e}"
        )
        return False
