"""Owner Configuration APIs.

Per-owner NL2SQL settings: tier, the caps NL2SQL can enforce, and whether the service is
enabled for them. Ported from fs-agent-usage-limits' `routers/owner_config_router.py`,
reduced to what NL2SQL can answer for itself.

Endpoints:
  GET   /v1/owners/{owner_id}/config         current settings (defaults when unset)
  PUT   /v1/owners/{owner_id}/config         replace — omitted fields return to defaults
  PATCH /v1/owners/{owner_id}/config         update only what is sent
  GET   /v1/owners/{owner_id}/usage/status   settings + live usage + headroom
  GET   /v1/owners/{owner_id}/limits         the Usage screen's Limits tab, in one read

Three things worth knowing:

* **GET never 404s.** An owner with no row gets the defaults, flagged `is_default: true`.
  A customer who has never been configured is usable immediately.

* **Writes are master-key only.** Caps are commercial terms; a customer must not be able
  to raise their own. Reads are open to a session so the dashboard can show them.

* **`usage/status` REPORTS, it does not enforce.** Nothing here blocks a request.
  `max_queries_per_day` IS enforced, but elsewhere: `POST /v1/agents/{agent_id}/chat`
  and `POST /v1/csv_agent/api/chat` refuse with 429 past it. The other caps are
  reported only — nothing checks them.

Not carried over: `POST /v1/owners/register`, `services/enable`, `services/disable`.
Those provision an owner across all six services, which is not NL2SQL's to decide.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path

from api.v1.schemas.owner_config import (
    CurrentUsage,
    OwnerConfigResponse,
    OwnerConfigUpdate,
    PlatformLimits,
    RemainingQuota,
    UsageStatusResponse,
)
from api.v1.schemas.owner_limits import OwnerLimitsResponse
from chatbot_management.db_utils.owner_config_db_utils import (
    get_current_usage,
    get_owner_config,
    upsert_owner_config,
)
from chatbot_management.db_utils.owner_limits_db_utils import get_owner_limits
from chatbot_management.services.sqlmodel_session import async_session
from chatbot_management.utils.api_validation import get_api_key_or_session
from logger import logger
from otel_tracing import track_time

router = APIRouter(prefix="/v1/owners", tags=["Owner Configuration"])


def _resolve_owner(auth: dict, owner_id: str) -> str:
    """Which owner this request is about.

    Resolution, not authorization — see `agent/utils/authorization.py`, where RBAC is off
    because the chat service 404s on agents NL2SQL created. Lower-cased because this repo
    stores owner emails that way everywhere and matches them exactly.
    """
    if owner_id == "me":
        resolved = auth.get("user_id")
        if not resolved:
            raise HTTPException(
                status_code=400,
                detail="owner_id 'me' requires a session; name the owner explicitly with an API key",
            )
        owner_id = resolved
    owner_id = (owner_id or "").strip().lower()
    # A browser session reads only its own settings and usage; master-key callers name
    # the owner explicitly.
    if auth.get("auth_type") == "session" and owner_id != (auth.get("user_id") or "").strip().lower():
        raise HTTPException(status_code=403, detail="A session may only read its own owner settings")
    return owner_id


def _require_master_key(auth: dict) -> None:
    """Writes are master-key only — an owner must not be able to raise their own caps."""
    if auth.get("auth_type") != "master_api_key":
        raise HTTPException(
            status_code=403,
            detail="Changing owner configuration requires the master API key",
        )


@router.get("/{owner_id}/config", response_model=OwnerConfigResponse)
@track_time("API: Get Owner Config")
async def api_get_owner_config(
    owner_id: str = Path(..., description="Owner email, or 'me' for the caller"),
    auth: dict = Depends(get_api_key_or_session),
) -> OwnerConfigResponse:
    """This owner's NL2SQL settings. Returns defaults (`is_default: true`) when unset."""
    target = _resolve_owner(auth, owner_id)
    try:
        async with async_session() as session:
            return OwnerConfigResponse(**await get_owner_config(session, target))
    except Exception as e:
        logger.error(f"GET config for {target} - Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An unexpected error occurred")


@router.put("/{owner_id}/config", response_model=OwnerConfigResponse)
@track_time("API: Replace Owner Config")
async def api_put_owner_config(
    payload: OwnerConfigUpdate,
    owner_id: str = Path(...),
    auth: dict = Depends(get_api_key_or_session),
) -> OwnerConfigResponse:
    """Replace the configuration. Anything omitted returns to its DEFAULT, not its
    current value — send the full object, or use PATCH."""
    _require_master_key(auth)
    return await _save(payload, owner_id, auth, replace=True)


@router.patch("/{owner_id}/config", response_model=OwnerConfigResponse)
@track_time("API: Update Owner Config")
async def api_patch_owner_config(
    payload: OwnerConfigUpdate,
    owner_id: str = Path(...),
    auth: dict = Depends(get_api_key_or_session),
) -> OwnerConfigResponse:
    """Change only the fields provided; everything else is left as it is."""
    _require_master_key(auth)
    return await _save(payload, owner_id, auth, replace=False)


async def _save(payload: OwnerConfigUpdate, owner_id: str, auth: dict, *, replace: bool):
    target = _resolve_owner(auth, owner_id)
    limits = payload.platform_limits.model_dump(exclude_unset=True) if payload.platform_limits else None
    try:
        async with async_session() as session:
            saved = await upsert_owner_config(
                session, target,
                tier_type=payload.tier_type,
                base_tier=payload.base_tier,
                limits=limits,
                provider_key_source=payload.provider_key_source,
                acting_user=auth.get("user_id") or "master_api_key",
                replace=replace,
            )
        return OwnerConfigResponse(**saved)
    except Exception as e:
        logger.error(f"Save config for {target} - Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An unexpected error occurred")


@router.get("/{owner_id}/limits", response_model=OwnerLimitsResponse)
@track_time("API: Owner Limits")
async def api_get_owner_limits(
    owner_id: str = Path(..., description="Owner email, or 'me' for the caller"),
    auth: dict = Depends(get_api_key_or_session),
) -> OwnerLimitsResponse:
    """Everything the Usage screen's Limits tab renders, in one read.

    Grouped rows, each with its usage, its ceiling in words, and how it is lifted. Two
    behaviours the UI must respect rather than re-derive:

    * **A `lifted` item has `percent: null` and must be drawn with no progress bar.** A bar
      against a ceiling nobody is enforcing is a lie the reader can act on. `maximum`
      still states the ceiling, so lifted never means hiding what the cap is.

    * **Only `enforced` items have a consequence.** `queries_per_day` is the sole cap that
      blocks: past it, chat returns 429. Everything else is reporting, and rendering it as
      though it stops something invents a consequence.

    Neither the consumption-source filter nor the period selector applies to this tab.
    A limit counts every request the platform served, whichever key paid for it, and the
    window is fixed and stated in `billing_window` because a ceiling anchored to a window
    the reader can change is meaningless.

    The token and cost ceilings count PLATFORM-key work only, which is what makes
    "lifted by your own key" a real change rather than a label: bring a key and that
    provider's work stops counting toward them.
    """
    target = _resolve_owner(auth, owner_id)
    try:
        async with async_session() as session:
            return OwnerLimitsResponse(**await get_owner_limits(session, target))
    except Exception as e:
        logger.error(f"GET limits for {target} - Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An unexpected error occurred")


@router.get("/{owner_id}/usage/status", response_model=UsageStatusResponse)
@track_time("API: Owner Usage Status")
async def api_get_usage_status(
    owner_id: str = Path(..., description="Owner email, or 'me' for the caller"),
    auth: dict = Depends(get_api_key_or_session),
) -> UsageStatusResponse:
    """Caps, live usage and remaining headroom — what the Usage & Limits screen needs.

    Counted from NL2SQL's own tables: agents from `chatbot_details`, tokens from
    `nl2sql_agent_health_events` (calendar month to date), team members from
    `chatbot_invitations`, and queries from `nl2sql_logs` plus CSV-agent events over the
    rolling 24 hours ending now.

    `exceeded` names caps with no headroom left. This endpoint only REPORTS, but one of
    those caps does block: `queries_last_24h` appearing in `exceeded` means chat is
    currently returning 429 for this owner. `current_usage.queries_reset_at` says when they
    next regain an allowance.
    """
    target = _resolve_owner(auth, owner_id)
    try:
        async with async_session() as session:
            cfg = await get_owner_config(session, target)
            usage = await get_current_usage(session, target)
    except Exception as e:
        logger.error(f"GET usage/status for {target} - Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An unexpected error occurred")

    limits = cfg["platform_limits"]
    # Pair each cap with the count that measures it.
    pairs = {
        "agents": (limits.get("max_agents"), usage["agents"]),
        "tokens_this_month": (limits.get("max_llm_tokens_per_month"), usage["tokens_this_month"]),
        "team_members": (limits.get("max_team_members"), usage["team_members"]),
        "queries_last_24h": (limits.get("max_queries_per_day"), usage["queries_last_24h"]),
    }
    # None cap = unlimited, so headroom is None rather than 0 — a UI must not render
    # "0 remaining" for something uncapped. Headroom floors at 0 so an over-cap owner
    # shows no headroom rather than a negative number.
    remaining = {k: (None if cap is None else max(0, cap - used)) for k, (cap, used) in pairs.items()}
    # `used >= cap`, not `>`: a cap of 20 permits 20 queries, so at 20 the allowance is
    # spent. This must match `check_query_allowed`, or the dashboard would show no breach
    # on the exact request chat refuses.
    exceeded = [k for k, (cap, used) in pairs.items() if cap is not None and used >= cap]

    return UsageStatusResponse(
        owner_id=target,
        tier_type=cfg["tier_type"],
        limits=PlatformLimits(**limits),
        current_usage=CurrentUsage(**usage),
        remaining=RemainingQuota(**remaining),
        exceeded=exceeded,
    )
