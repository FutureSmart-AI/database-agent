"""Free sample-data questions: per-user allowance and a global monthly budget.

A demo agent (`chatbot_details.is_demo`) is listed for every signed-in user and runs on
the platform model key, because the provider key follows the agent's owner
(`agent.utils.provider_key_scope`). That is what lets a visitor ask questions without a key
or a database. This module bounds what it costs:

- each signed-in user may ask DEMO_DAILY_QUESTIONS per rolling 24 hours and
  DEMO_TOTAL_QUESTIONS in total, across every demo agent;
- all demo questions together stop once this calendar month's spend reaches
  DEMO_MONTHLY_BUDGET_USD.

WHO IS COUNTED. The user asking, never the demo agent's owner: the owner's own query cap
would make every visitor share one allowance. The owner asking their own demo agent is not
a demo question and keeps the owner's normal cap (`demo_question_user`).

BEFORE THE MODEL CALL. `reserve_demo_question` writes the question's row before anything is
spent, inside a transaction holding one advisory lock, so two questions sent at once are
counted one after the other: neither can pass on a count that leaves out the other. The lock
covers the count and the insert, a few milliseconds, never the answer itself.

SPEND per question, from the health event with the same `chat_id`, in this order:
1. `cost_usd`, when LangSmith priced the run;
2. else its recorded `total_tokens` at the product's blended estimate rate
   (`usage_limits.TOKEN_RATE_USD`, the rate the Usage & Limits screen prices tokens at).
   LangSmith tracing is off on the hosted service, so this is the normal case there: no
   hosted question has carried a `cost_usd` since 2026-10-02;
3. else, while the question is still running and nothing is recorded yet,
   DEMO_UNPRICED_COST_USD, set above the most expensive question measured, so a question in
   flight is never counted as free.

INTERNAL ACCOUNTS. A signed-in user whose VERIFIED email is on one of
DEMO_INTERNAL_DOMAINS (aidemos.com and futuresmart.ai: the AI Demos researchers and the
FutureSmart team) has no daily or lifetime limit, so testing never needs a manual reset.
Their questions are still reserved and recorded, with `audience = 'internal'`, and their cost
is reported separately; they are not counted against the public monthly budget, which stays
for public free usage. "Verified" means the identity token the auth service validated says
`email_verified: true` for that same email, and the domain is compared exactly: a
subdomain, a look-alike (`futuresmart.ai.example.com`) or a master-key caller declaring a user
is never internal (`demo_audience`).

FAILS CLOSED. Unlike the owner cap, any error while checking refuses the question: these
questions are paid by FutureSmart, so an unreadable allowance must not become an unlimited one.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


DAILY_LIMIT = _int_env("DEMO_DAILY_QUESTIONS", 20)
TOTAL_LIMIT = _int_env("DEMO_TOTAL_QUESTIONS", 100)
MONTHLY_BUDGET_USD = _float_env("DEMO_MONTHLY_BUDGET_USD", 150.0)
# Above the most expensive answered question measured on the hosted service ($0.068), so a
# question still running is never under-counted.
UNPRICED_COST_USD = _float_env("DEMO_UNPRICED_COST_USD", 0.07)
INTERNAL_DOMAINS = frozenset(
    d.strip().lower() for d in os.getenv("DEMO_INTERNAL_DOMAINS", "aidemos.com,futuresmart.ai").split(",")
    if d.strip())

PUBLIC = "public"
INTERNAL = "internal"

# The cost of one question: recorded cost, else recorded tokens at the blended rate, else the
# in-flight estimate. `h` is its health event (left-joined, so it may be missing).
_QUESTION_COST = ("coalesce(h.cost_usd, h.total_tokens * CAST(:token_rate AS double precision), "
                  "CAST(:unpriced AS double precision))")
# The casts matter: next to an integer column asyncpg infers an untyped parameter as an
# integer, which turned the per-token rate into 0 and priced every question at nothing.


def _cost_params() -> Dict[str, float]:
    from chatbot_management.utils.usage_limits import TOKEN_RATE_USD
    return {"token_rate": TOKEN_RATE_USD, "unpriced": UNPRICED_COST_USD}

# One fixed key: the whole allowance-and-budget check is serialised, not per user,
# because the monthly budget is shared by everyone.
_LOCK_KEY = 4_173_909_201

# Statuses that use up the user's allowance. A question that failed on our side is not
# charged to the user, but its cost still counts against the budget.
_COUNTED = "('reserved', 'answered')"

BYOK_HINT = (
    "To keep going, add your own OpenAI key under Credentials and connect your own "
    "database, or run Database Agent yourself from the open-source repository."
)


@dataclass
class DemoRefusal(Exception):
    """Why a demo question was refused. `reason`: daily | total | budget | unavailable."""
    reason: str
    message: str
    status: Dict[str, Any]

    def __str__(self) -> str:  # pragma: no cover - for logs
        return f"{self.reason}: {self.message}"


def demo_question_user(agent: Any, auth_type: Optional[str], user_id: Optional[str]) -> Optional[str]:
    """The user a question on `agent` is charged to as a free demo question, or None.

    None when the agent is not a demo agent, or when the caller is its owner (they keep the
    owner's own cap), or a master-key caller acting as nobody (an administrator).

    A caller that is not the owner but has no identity is returned as "" so the caller
    refuses it: an anonymous question cannot be counted against anyone.
    """
    if not getattr(agent, "is_demo", False):
        return None
    owner = (getattr(agent, "owner_id", "") or "").strip().lower()
    user = (user_id or "").strip().lower()
    if auth_type == "master_api_key" and not user:
        return None
    if user and user == owner:
        return None
    return user


def _claim_true(value: Any) -> bool:
    return value is True or (isinstance(value, str) and value.strip().lower() == "true")


def demo_audience(auth: Optional[Dict[str, Any]]) -> str:
    """'internal' when the caller is a signed-in user with a verified email on an internal
    domain, else 'public'.

    Only a session caller qualifies: its claims come from the identity token the auth service
    validated. The claims' own email must be the session's user, `email_verified` must be
    true, and the part after the last '@' must equal an internal domain exactly.
    """
    if not auth or auth.get("auth_type") != "session":
        return PUBLIC
    session_data = auth.get("session_data") or {}
    claims = session_data.get("all_claims") or {}
    email = (claims.get("email") or "").strip().lower()
    user = (auth.get("user_id") or "").strip().lower()
    if not email or email != user or not _claim_true(claims.get("email_verified")):
        return PUBLIC
    local, _, domain = email.rpartition("@")
    if not local or domain not in INTERNAL_DOMAINS:
        return PUBLIC
    return INTERNAL


async def _month_public_spend(session: AsyncSession) -> float:
    return float((await session.execute(text(f"""
        select coalesce(sum({_QUESTION_COST}), 0)
        from nl2sql_demo_questions q
        left join nl2sql_agent_health_events h on h.chat_id = q.chat_id
        where q.created_at >= date_trunc('month', now() at time zone 'utc')
          and q.audience = 'public'
    """), _cost_params())).scalar_one())


async def _usage(session: AsyncSession, user_id: str, audience: str = PUBLIC) -> Dict[str, Any]:
    row = (await session.execute(text(f"""
        select
          count(*) filter (where created_at > (now() at time zone 'utc') - interval '24 hours') as today,
          count(*) as total,
          min(created_at) filter (where created_at > (now() at time zone 'utc') - interval '24 hours') as oldest_today
        from nl2sql_demo_questions
        where user_id = :user_id and status in {_COUNTED}
    """), {"user_id": user_id})).one()
    today, total, oldest_today = int(row.today), int(row.total), row.oldest_today
    if audience == INTERNAL:
        return {
            "audience": INTERNAL, "unlimited": True,
            "daily_limit": None, "daily_used": today, "daily_remaining": None,
            "daily_resets_at": None,
            "total_limit": None, "total_used": total, "total_remaining": None,
            "budget_open": True,
        }
    spent = await _month_public_spend(session)
    resets_at = None
    if today >= DAILY_LIMIT and oldest_today is not None:
        from datetime import timedelta
        resets_at = (oldest_today + timedelta(hours=24)).isoformat(timespec="seconds") + "Z"
    return {
        "audience": PUBLIC, "unlimited": False,
        "daily_limit": DAILY_LIMIT,
        "daily_used": today,
        "daily_remaining": max(DAILY_LIMIT - today, 0),
        "daily_resets_at": resets_at,
        "total_limit": TOTAL_LIMIT,
        "total_used": total,
        "total_remaining": max(TOTAL_LIMIT - total, 0),
        "budget_open": float(spent) + UNPRICED_COST_USD <= MONTHLY_BUDGET_USD,
        "_month_spend_usd": float(spent),
    }


def public_status(status: Dict[str, Any]) -> Dict[str, Any]:
    """The allowance as shown to the user: never the spend figure itself."""
    return {k: v for k, v in status.items() if not k.startswith("_")}


def _refusal(status: Dict[str, Any]) -> Optional[DemoRefusal]:
    if status.get("unlimited"):
        return None
    if status["total_used"] >= TOTAL_LIMIT:
        return DemoRefusal("total", (
            f"You have used all {TOTAL_LIMIT} free sample-data questions on this account. "
            + BYOK_HINT), public_status(status))
    if status["daily_used"] >= DAILY_LIMIT:
        when = (status["daily_resets_at"] or "").replace("T", " ")[:16]
        return DemoRefusal("daily", (
            f"You have used today's {DAILY_LIMIT} free sample-data questions"
            + (f"; more are available after {when} UTC. " if when else ". ") + BYOK_HINT),
            public_status(status))
    if not status["budget_open"]:
        return DemoRefusal("budget", (
            "Free sample-data questions are paused for the rest of this month. "
            + BYOK_HINT), public_status(status))
    return None


async def reserve_demo_question(session: AsyncSession, *, user_id: str, agent_id: str,
                                chat_id: str, request_id: Optional[str],
                                audience: str = PUBLIC) -> Dict[str, Any]:
    """Count this question against `user_id` and the budget, or raise DemoRefusal.

    An internal user's question is recorded the same way but never refused (see INTERNAL
    ACCOUNTS above). Returns the allowance AFTER this question. Commits on success; the row
    is the reservation and must later be closed with `finish_demo_question`.
    """
    audience = INTERNAL if audience == INTERNAL else PUBLIC
    async with session.begin():
        await session.execute(text("select pg_advisory_xact_lock(:k)"), {"k": _LOCK_KEY})
        status = await _usage(session, user_id, audience)
        refusal = _refusal(status)
        if refusal is not None:
            raise refusal
        await session.execute(text("""
            insert into nl2sql_demo_questions
              (chat_id, user_id, agent_id, request_id, status, audience)
            values (:chat_id, :user_id, :agent_id, :request_id, 'reserved', :audience)
        """), {"chat_id": chat_id, "user_id": user_id, "agent_id": agent_id,
               "request_id": request_id, "audience": audience})
    status["daily_used"] += 1
    status["total_used"] += 1
    if not status["unlimited"]:
        status["daily_remaining"] = max(DAILY_LIMIT - status["daily_used"], 0)
        status["total_remaining"] = max(TOTAL_LIMIT - status["total_used"], 0)
    return public_status(status)


async def finish_demo_question(session: AsyncSession, chat_id: str, *, answered: bool) -> None:
    """Close a reservation. A failed question stops counting against the user's allowance."""
    async with session.begin():
        await session.execute(text("""
            update nl2sql_demo_questions
               set status = :status, finished_at = (now() at time zone 'utc')
             where chat_id = :chat_id and status = 'reserved'
        """), {"status": "answered" if answered else "failed", "chat_id": chat_id})


async def demo_allowance(session: AsyncSession, user_id: str,
                         audience: str = PUBLIC) -> Dict[str, Any]:
    """The signed-in user's remaining free questions, for the UI."""
    return public_status(await _usage(session, user_id, audience))


async def demo_usage_summary(session: AsyncSession) -> Dict[str, Any]:
    """The milestone's adoption measurements, from the question rows and existing tables.

    - first_question: users who asked at least one demo question
    - explored_3: users who asked three or more
    - returning: users who asked on two or more different UTC days
    - converted_key / converted_agent: users who, after their first demo question, saved a
      provider key, or created an agent of their own
    - spend: every demo question's cost (recorded, else tokens at the blended rate), its
      tokens, and how many questions each pricing source covered

    Reported separately for public users and internal accounts (`audience`), so the team's
    own testing never inflates the adoption figures or hides in the public spend.
    """
    return {
        "public": await _audience_summary(session, PUBLIC),
        "internal": await _audience_summary(session, INTERNAL),
        "limits": {"daily": DAILY_LIMIT, "total": TOTAL_LIMIT,
                   "monthly_budget_usd": MONTHLY_BUDGET_USD,
                   "budget_applies_to": PUBLIC,
                   "internal_domains": sorted(INTERNAL_DOMAINS),
                   "unpriced_cost_usd": UNPRICED_COST_USD,
                   "token_rate_usd": _cost_params()["token_rate"]},
    }


async def _audience_summary(session: AsyncSession, audience: str) -> Dict[str, Any]:
    params = {"audience": audience}
    users = (await session.execute(text(f"""
        with per_user as (
          select user_id, count(*) as n, count(distinct created_at::date) as days,
                 min(created_at) as first_at
          from nl2sql_demo_questions
          where status in {_COUNTED} and audience = :audience
          group by user_id
        )
        select
          count(*) as first_question,
          count(*) filter (where n >= 3) as explored_3,
          count(*) filter (where days >= 2) as returning,
          count(*) filter (where exists (
            select 1 from user_provider_keys k
             where lower(k.owner_id) = per_user.user_id
               and k.created_at > (per_user.first_at at time zone 'utc'))) as converted_key,
          count(*) filter (where exists (
            select 1 from chatbot_details c
             where lower(c.owner_id) = per_user.user_id
               and coalesce(c.is_demo, false) = false and c.deleted = false
               and c.created_at > per_user.first_at)) as converted_agent
        from per_user
    """), params)).one()
    spend = (await session.execute(text("""
        select
          count(*) as questions,
          count(*) filter (where q.status = 'answered') as answered,
          count(*) filter (where q.status = 'failed') as failed,
          coalesce(sum(h.total_tokens), 0) as tokens,
          coalesce(sum(h.cost_usd), 0) as recorded_cost_usd,
          count(h.cost_usd) as priced_by_langsmith,
          count(*) filter (where h.cost_usd is null and h.total_tokens is not null) as priced_from_tokens,
          count(*) filter (where h.cost_usd is null and h.total_tokens is null) as unpriced,
          coalesce(sum({cost}), 0) as spend_usd,
          coalesce(sum({cost})
                   filter (where q.created_at >= date_trunc('month', now() at time zone 'utc')), 0)
            as month_spend_usd
        from nl2sql_demo_questions q
        left join nl2sql_agent_health_events h on h.chat_id = q.chat_id
        where q.audience = :audience
    """.replace("{cost}", _QUESTION_COST)), {**_cost_params(), **params})).one()
    return {
        "users": dict(users._mapping),
        "questions": {k: (float(v) if k.endswith("_usd") else int(v))
                      for k, v in spend._mapping.items()},
    }
