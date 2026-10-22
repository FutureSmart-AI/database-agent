"""
Business logic for agent invitations management.

This used to delegate to `user_admin_management.db_utils.invitation_db_utils` — a module that does
not exist in this repository, so every one of these endpoints raised ModuleNotFoundError. The work
now goes to `agent.db_utils.invitation_db_utils`, which owns the roles locally instead of asking
the chat service.
"""
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from chatbot_management.services.logger import logger


def resolve_actor(auth: dict, user: dict) -> Optional[str]:
    """Who is making this call, for the audit trail.

    Session callers are identified by their signed-in address. A master-key caller has no identity
    of its own, so the actor is left unset rather than attributed to the owner — the audit line
    then says `unknown`, which is the truth.
    """
    if (auth or {}).get("auth_type") == "master_api_key":
        return None
    return (auth or {}).get("user_id") or (user or {}).get("email")


async def get_agent_owner_email(agent_id: str) -> Optional[str]:
    """The agent's owner address, or None when it cannot be established.

    None is a real outcome, not an error: `owner_id` is `"unknown"` on a large share of older
    agents. Callers that need a definite grantor turn it into a 400.
    """
    from agent.db_utils.invitation_db_utils import resolve_agent_owner

    agent = await resolve_agent_owner(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    return agent["owner_email"]


async def create_agent_invitation(
    agent_id: str,
    invitations: List[Dict[str, Any]],
    actor: Optional[str] = None,
) -> dict:
    from agent.db_utils.invitation_db_utils import create_invitations

    if not invitations:
        raise HTTPException(status_code=400, detail="At least one email address is required")

    logger.info(f"Inviting {len(invitations)} user(s) to agent {agent_id} by {actor or 'master key'}")

    try:
        result = await create_invitations(agent_id, invitations, actor=actor)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    invited = result["invited_users"]
    failures = result["failed_emails"]

    if invited and failures:
        message = "Invitations sent with some failures"
    elif invited:
        message = "Invitations sent successfully"
    else:
        message = "Invitations failed"

    logger.info(
        f"Invitations completed agent_id={agent_id} invited={len(invited)} failed={len(failures)}"
    )
    return {
        "message": message,
        "invited_users": invited,
        # Bare addresses for clients expecting the chat service shape; the reasons alongside.
        "failed_emails": [f.get("email") for f in failures],
        "failures": failures,
    }


async def get_agent_invitations(agent_id: str) -> dict:
    from agent.db_utils.invitation_db_utils import list_invitations, resolve_agent_owner

    if not await resolve_agent_owner(agent_id):
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    invited_users = await list_invitations(agent_id)
    logger.info(f"Listed {len(invited_users)} collaborator(s) for agent {agent_id}")
    return {"invited_users": invited_users}


async def remove_agent_invitation(
    agent_id: str,
    invited_email: str,
    actor: Optional[str] = None,
) -> dict:
    from agent.db_utils.invitation_db_utils import delete_invitation

    removed = await delete_invitation(agent_id, invited_email, actor=actor)
    if not removed:
        raise HTTPException(status_code=404, detail="Invitation not found")

    return {"message": "Invitation removed successfully"}


async def update_agent_invitation_role(
    agent_id: str,
    invited_email: str,
    role: str,
    actor: Optional[str] = None,
) -> dict:
    from agent.db_utils.invitation_db_utils import update_invitation_role

    try:
        updated = await update_invitation_role(agent_id, invited_email, role, actor=actor)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if not updated:
        raise HTTPException(status_code=404, detail="Invitation not found")

    return {
        "message": "Role updated successfully",
        "email": updated["email"],
        "role": updated["role"],
        "previous_role": updated["previous_role"],
    }
