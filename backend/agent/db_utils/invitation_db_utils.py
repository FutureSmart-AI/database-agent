"""Collaborators on an agent: who is invited, at what role, and what role a caller holds.

NL2SQL used to leave sharing to the chat service — `require_agent_permission` asked its
`/auth/check-access` who the caller was, and the roles lived in the chat service's own
`agent_invitations` table. That made agents created through `POST /v1/agents` unusable, so the call
was dropped (see `agent.utils.authorization`). This module is the local replacement: the roles live
in our `chatbot_invitations`, and `get_agent_access_role` answers the same question without leaving
the process.

Two conventions the whole module depends on:

- **Emails are stored and compared lowercased.** A row written as `Foo@x.com` would never match a
  caller signing in as `foo@x.com`, which reads as "invited, but denied everything". Writes
  normalise; reads compare on `lower()`, so rows predating the normalisation still resolve.
- **Owners are not rows here.** Ownership is `chatbot_details.owner_id`; only invited collaborators
  get a row. `get_agent_access_role` checks ownership first and never expects to find the owner
  among the invitations.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import and_, or_, select

from agent.services.sqlmodel_session import get_async_session
from logger import logger
from models.sql_models import ChatbotDetails, ChatbotInvitations, Users
from otel_tracing import track_time

# The only roles an invitation can carry. `owner` is deliberately absent: it is not grantable —
# it is a property of the agent row — so accepting it here would create a second, contradictory
# source of ownership.
VALID_ROLES = ("viewer", "editor")
DEFAULT_ROLE = "viewer"


def normalize_email(email: Optional[str]) -> Optional[str]:
    """Lowercase and trim, or None. Every email crossing this module goes through here."""
    if not email:
        return None
    cleaned = email.strip().lower()
    return cleaned or None


def normalize_role(role: Optional[str]) -> str:
    """Coerce a role to a known value, defaulting to the least privileged one.

    Raises ValueError on an unrecognised non-empty role so a typo in the request body is a 400
    rather than a silently created invitation nobody can act on.
    """
    if role is None or role == "":
        return DEFAULT_ROLE
    cleaned = str(role).strip().lower()
    if cleaned not in VALID_ROLES:
        raise ValueError(f"Invalid role '{role}'. Expected one of: {', '.join(VALID_ROLES)}")
    return cleaned


def _agent_match(agent_id: str):
    """Match an invitation to an agent.

    Rows are written with both `agent_id` and `chatbot_id`, but rows predating the RESTful
    `agent_id` column carry only `chatbot_id`, so both are checked — the same rule
    `session_db_utils` and `api_key_db_utils` already apply.
    """
    return or_(ChatbotInvitations.agent_id == agent_id, ChatbotInvitations.chatbot_id == agent_id)


def _email_match(email: str):
    """Compare on `lower()` rather than `==` so rows written before normalisation still match."""
    return func.lower(ChatbotInvitations.invited_user_email) == email


def _invitation_payload(row: ChatbotInvitations) -> Dict[str, Any]:
    """One collaborator, in the single shape every endpoint reports.

    Creating and listing return identical records. They did not at first — create reported only the
    email and role, so the dashboard saw `invited_by` and `invited_at` as null on the response to
    its own POST and had to re-list to fill them in.
    """
    return {
        "email": row.invited_user_email,
        "role": row.role or DEFAULT_ROLE,
        "invited_by": row.invited_by_email,
        "invited_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@track_time("DB: Resolve Agent Owner")
async def resolve_agent_owner(agent_id: str) -> Optional[Dict[str, Any]]:
    """Identify an agent and its owner in one lookup: `{chatbot_id, owner_email, owner_id}`.

    `owner_id` normally holds the owner's email, but on a large share of older agents it holds a
    `user_id` — or the literal `"unknown"`. Only the first case can be resolved directly; the second
    is looked up through `users`, and the third yields `owner_email = None`, which callers must
    treat as "ownership cannot be established" rather than as "no owner".

    Returns None when the agent does not exist or is deleted — the caller turns that into a 404.
    """
    async for session in get_async_session():
        result = await session.execute(
            select(ChatbotDetails).where(
                or_(ChatbotDetails.agent_id == agent_id, ChatbotDetails.chatbot_id == agent_id),
                ChatbotDetails.deleted == False,  # noqa: E712 — SQL comparison, not a Python bool test
            )
        )
        agent = result.scalars().first()
        if not agent:
            return None

        owner_id = agent.owner_id
        owner_email = normalize_email(owner_id) if owner_id and "@" in str(owner_id) else None

        if not owner_email:
            # owner_id is a user_id (or absent) — go through `users` for the address.
            lookup_id = owner_id or agent.user_id
            if lookup_id and str(lookup_id).lower() != "unknown":
                user_result = await session.execute(
                    select(Users.email_id).where(Users.user_id == lookup_id)
                )
                owner_email = normalize_email(user_result.scalar_one_or_none())

        return {
            "chatbot_id": agent.chatbot_id,
            "agent_id": agent.agent_id or agent.chatbot_id,
            "owner_id": owner_id,
            "owner_email": owner_email,
        }


@track_time("DB: Create Invitations")
async def create_invitations(
    agent_id: str,
    invitations: List[Dict[str, Any]],
    invited_by_email: Optional[str] = None,
    actor: Optional[str] = None,
) -> Dict[str, Any]:
    """Invite one or more people to an agent.

    `invitations` is a list of `{"email": ..., "role": ...}`. Each is committed on its own so one
    bad address does not discard the rest of the batch; the outcome is reported per email in
    `invited_users` / `failed_emails`.

    **Re-inviting someone already invited is not an error.** It applies the role given, so the call
    is idempotent and the Share screen's "Add" behaves the same whether or not the person is already
    a collaborator. The chat service returned a failure here, which surfaced as an unexplained
    "Invitation is failed" whenever a user re-added an existing collaborator.

    `invited_by_email` records who granted access: the agent's owner where one can be resolved, and
    otherwise the caller. `actor` is the signed-in user actually making the call — the two differ
    when an admin invites on the owner's behalf, so both are kept.
    """
    agent = await resolve_agent_owner(agent_id)
    if not agent:
        raise LookupError(f"Agent {agent_id} not found")

    # Left NULL for master-key and internal callers, matching what `updated_by` means on every
    # other table in this schema. Attributing their writes to the owner would put an email in the
    # audit trail belonging to somebody who did not make the change.
    acting_user = normalize_email(actor)

    # Falling back to the caller is not a formality: 11% of production agents have a NULL
    # `owner_id`, and their `user_id` is an auth-service UUID with no row in our `users` table, so
    # no owner email can be derived for them at all. Insisting on the owner would make those agents
    # permanently unshareable. The signed-in caller did grant the access, so recording them is
    # accurate — and the agent is identified by `agent_id` regardless, so nothing is ambiguous.
    granted_by = normalize_email(invited_by_email) or agent["owner_email"] or acting_user
    if not granted_by:
        raise ValueError(
            "Cannot determine who is granting access: this agent has no resolvable owner and the "
            "caller is unidentified. Call with a signed-in session rather than the master key."
        )

    invited_users: List[Dict[str, Any]] = []
    failed_emails: List[Dict[str, str]] = []

    async for session in get_async_session():
        for item in invitations or []:
            email = normalize_email(item.get("email"))
            if not email:
                failed_emails.append({"email": item.get("email"), "reason": "Email is required"})
                continue

            try:
                role = normalize_role(item.get("role"))
            except ValueError as exc:
                failed_emails.append({"email": email, "reason": str(exc)})
                continue

            try:
                existing_result = await session.execute(
                    select(ChatbotInvitations).where(
                        and_(_agent_match(agent_id), _email_match(email))
                    )
                )
                existing = existing_result.scalars().first()

                if existing:
                    previous_role = existing.role
                    existing.role = role
                    existing.updated_at = datetime.utcnow()
                    existing.updated_by = acting_user
                    # Backfill agent_id on a legacy row while we are writing to it anyway.
                    if not existing.agent_id:
                        existing.agent_id = agent["agent_id"]
                    session.add(existing)
                    await session.commit()
                    invited_users.append(_invitation_payload(existing))
                    logger.info(
                        f"[audit] invitation reapplied agent_id={agent_id} email={email} "
                        f"role={previous_role}->{role} by={acting_user or 'unknown'}"
                    )
                    continue

                invitation = ChatbotInvitations(
                    chatbot_id=agent["chatbot_id"],
                    agent_id=agent["agent_id"],
                    invited_user_email=email,
                    invited_by_email=granted_by,
                    role=role,
                    updated_by=acting_user,
                )
                session.add(invitation)
                await session.commit()
                # Safe to read after commit: the session factory sets expire_on_commit=False, so
                # the defaulted created_at/updated_at are already on the instance.
                invited_users.append(_invitation_payload(invitation))
                logger.info(
                    f"[audit] invitation created agent_id={agent_id} email={email} "
                    f"role={role} by={acting_user or 'unknown'}"
                )
            except IntegrityError as exc:
                # Usually two concurrent invites for the same person: the unique index added by
                # `add_invitation_roles` rejects the loser, and the row exists either way — which is
                # what the caller asked for, so that is a success, not a phantom failure.
                #
                # Confirmed rather than assumed. A unique violation is not the only integrity error
                # possible (a primary-key collision from a lagging sequence would be another), and
                # reporting a row that was never written as invited is worse than a clear failure.
                await session.rollback()
                confirm = await session.execute(
                    select(ChatbotInvitations).where(
                        and_(_agent_match(agent_id), _email_match(email))
                    )
                )
                winner = confirm.scalars().first()
                if winner:
                    invited_users.append(_invitation_payload(winner))
                    logger.warning(
                        f"Invitation for {email} on {agent_id} lost a race; existing row kept: {exc}"
                    )
                else:
                    failed_emails.append({"email": email, "reason": "Could not be saved"})
                    logger.error(f"Invitation for {email} on {agent_id} failed integrity check: {exc}")
            except Exception as exc:
                await session.rollback()
                failed_emails.append({"email": email, "reason": "Could not be saved"})
                logger.error(f"Invitation insert failed for {email} on {agent_id}: {exc}")

    return {
        "owner_email": granted_by,
        "invited_users": invited_users,
        "failed_emails": failed_emails,
    }


@track_time("DB: List Invitations")
async def list_invitations(agent_id: str) -> List[Dict[str, Any]]:
    """Every collaborator on an agent, newest first.

    Deliberately not filtered by who sent the invitation. The chat service scoped its listing to
    `invited_by_email == owner`, which hid — and made unrevokable — any invitation sent by someone
    other than the current owner, including every row that survived an ownership change.
    """
    async for session in get_async_session():
        result = await session.execute(
            select(ChatbotInvitations)
            .where(_agent_match(agent_id))
            .order_by(ChatbotInvitations.created_at.desc())
        )
        return [_invitation_payload(row) for row in result.scalars().all()]


@track_time("DB: Delete Invitation")
async def delete_invitation(agent_id: str, invited_email: str, actor: Optional[str] = None) -> bool:
    """Revoke a collaborator's access. Returns False when there is nothing to revoke.

    A hard delete, matching the chat service: no row survives to carry a `deleted_by`, so the
    revocation is recorded in the `[audit]` log line instead — who was removed, at what role, by
    whom.
    """
    email = normalize_email(invited_email)
    if not email:
        return False

    async for session in get_async_session():
        result = await session.execute(
            select(ChatbotInvitations).where(and_(_agent_match(agent_id), _email_match(email)))
        )
        row = result.scalars().first()
        if not row:
            return False

        revoked_role = row.role
        await session.delete(row)
        await session.commit()
        logger.info(
            f"[audit] invitation revoked agent_id={agent_id} email={email} "
            f"role={revoked_role} by={normalize_email(actor) or 'unknown'} hard_delete=true"
        )
        return True


@track_time("DB: Update Invitation Role")
async def update_invitation_role(
    agent_id: str,
    invited_email: str,
    role: str,
    actor: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Change a collaborator's role. Returns None when they are not a collaborator.

    `updated_by` records who made the change, which is not necessarily `invited_by_email` — that
    names whoever sent the original invitation, possibly a previous owner.
    """
    email = normalize_email(invited_email)
    if not email:
        return None
    new_role = normalize_role(role)

    async for session in get_async_session():
        result = await session.execute(
            select(ChatbotInvitations).where(and_(_agent_match(agent_id), _email_match(email)))
        )
        row = result.scalars().first()
        if not row:
            return None

        previous_role = row.role
        acting_user = normalize_email(actor)
        row.role = new_role
        row.updated_at = datetime.utcnow()
        row.updated_by = acting_user
        session.add(row)
        await session.commit()

        logger.info(
            f"[audit] invitation role changed agent_id={agent_id} email={email} "
            f"role={previous_role}->{new_role} by={acting_user or 'unknown'}"
        )
        return {"email": email, "role": new_role, "previous_role": previous_role}


@track_time("DB: Resolve Access Role")
async def get_agent_access_role(
    agent_id: str,
    user_email: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Optional[str]:
    """The caller's role on an agent: `owner`, `editor`, `viewer`, or None for no access.

    Ownership is checked first and from the agent row, so an owner never depends on an invitation
    existing.

    ⚠ REPORTING ONLY — nothing authorizes on this. `require_agent_permission` still lets any valid
    login through (see its module docstring); this exists so a caller can be *shown* their standing
    on an agent. A None here does not stop anybody from reaching the agent.

    Note that an agent whose `owner_id` is unresolvable (`"unknown"`, a stale user_id) cannot prove
    ownership to anyone, so its real owner also resolves to None. Harmless while this is only
    reported; it would lock owners out if it ever became an access check, so backfill those agents
    before making it one.
    """
    email = normalize_email(user_email)
    if not email and not user_id:
        return None

    agent = await resolve_agent_owner(agent_id)
    if not agent:
        return None

    if user_id and agent["owner_id"] and str(agent["owner_id"]) == str(user_id):
        return "owner"

    if not email and user_id:
        async for session in get_async_session():
            user_result = await session.execute(
                select(Users.email_id).where(Users.user_id == user_id)
            )
            email = normalize_email(user_result.scalar_one_or_none())

    if not email:
        return None

    if agent["owner_email"] and agent["owner_email"] == email:
        return "owner"

    async for session in get_async_session():
        result = await session.execute(
            select(ChatbotInvitations.role).where(
                and_(_agent_match(agent_id), _email_match(email))
            )
        )
        role = result.scalars().first()
        if role:
            return str(role).strip().lower()

    return None


@track_time("DB: List Invited Agent Roles")
async def get_invited_agent_roles(user_email: str) -> Dict[str, str]:
    """Agents a user has been invited to, as `{agent_id: role}` — the "Shared with me" lookup.

    Returns identifiers rather than agents, so the caller can load them through the same formatter
    the owned list uses and a shared agent carries identical fields to an owned one.

    Both `agent_id` and `chatbot_id` are keyed where they differ: the agent list reports
    `chatbot_id` as its `agent_id`, while invitations written through the v1 API carry the real
    `agent_id`, and the caller should be able to match on either without knowing which it holds.
    """
    email = normalize_email(user_email)
    if not email:
        return {}

    async for session in get_async_session():
        result = await session.execute(
            select(
                ChatbotInvitations.agent_id,
                ChatbotInvitations.chatbot_id,
                ChatbotInvitations.role,
            ).where(_email_match(email))
        )
        roles: Dict[str, str] = {}
        for agent_id, chatbot_id, role in result.all():
            # Legacy rows carry only chatbot_id. `add_invitation_roles` backfills what it can, but
            # a row whose agent was deleted keeps a NULL agent_id, so fall back rather than drop it
            # — the agent lookup filters deleted agents out anyway.
            for identifier in (agent_id, chatbot_id):
                if identifier:
                    roles[identifier] = (role or DEFAULT_ROLE).strip().lower()
        return roles


async def is_user_authorized(agent_id: str, user_email: str) -> bool:
    """Whether a user has any access to an agent, at any role.

    Kept as the coarse check some older call sites want. Prefer `get_agent_access_role` where the
    specific role matters — this cannot distinguish a viewer from an owner.
    """
    return await get_agent_access_role(agent_id, user_email=user_email) is not None
