"""
RESTful API endpoints for agent invitations.

Sharing is NL2SQL's own now: the collaborators and their roles live in this service's
`chatbot_invitations`, not in the chat service's `agent_invitations`. The routes mirror the chat
service's so the dashboard's Share screen can be repointed without a frontend change.

Managing collaborators is deliberately not something an API key can do — `enforce_agent_key_restrictions`
rejects `agent_api_key` auth on every `/invitations` path, so a leaked key cannot hand out access.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path, status
from starlette.requests import Request

from api.v1.schemas.invitations import (
    CreateInvitationsResponse,
    DeleteInvitationResponse,
    InvitationsListResponse,
    InviteUsersRequest,
    RemoveInvitationRequest,
    UpdateRoleRequest,
    UpdateRoleResponse,
)
from agent.utils.authorization import require_agent_permission
from api.v1.utils.invitations_helper import (
    create_agent_invitation,
    get_agent_invitations,
    remove_agent_invitation,
    resolve_actor,
    update_agent_invitation_role,
)
from chatbot_management.services.logger import logger
from chatbot_management.utils.api_validation import get_api_key_or_session

router = APIRouter(prefix="/v1")


@router.post(
    "/agents/{agent_id}/invitations",
    response_model=CreateInvitationsResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_invitation(
    agent_id: str = Path(..., description="Agent ID"),
    body: InviteUsersRequest = None,
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("invite")),
):
    """
    Invite users to collaborate on an agent

    Each invitation carries a role — `viewer` or `editor`. Inviting somebody who is already a
    collaborator applies the new role rather than failing, so the call is safe to repeat.
    """
    try:
        if not body:
            raise HTTPException(status_code=400, detail="At least one email address is required")

        return await create_agent_invitation(
            agent_id,
            body.resolved_invitations(),
            actor=resolve_actor(auth, user),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Exception in create_invitation: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/agents/{agent_id}/invitations", response_model=InvitationsListResponse)
async def get_invitations(
    agent_id: str = Path(..., description="Agent ID"),
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("read")),
):
    """
    List an agent's collaborators

    Returns every invitation on the agent regardless of who sent it, so a collaborator invited by a
    previous owner is still visible and still revocable.
    """
    try:
        return await get_agent_invitations(agent_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Exception in get_invitations: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.delete(
    "/agents/{agent_id}/invitations/{invitation_id}",
    response_model=DeleteInvitationResponse,
)
async def delete_invitation(
    agent_id: str = Path(..., description="Agent ID"),
    invitation_id: str = Path(..., description="Invitation ID (invited user's email)"),
    body: Optional[RemoveInvitationRequest] = None,
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("invite")),
):
    """
    Remove a collaborator from an agent

    The invitation_id is the email address of the invited user. The row is deleted outright; the
    revocation is recorded in the audit log.
    """
    try:
        return await remove_agent_invitation(
            agent_id, invitation_id, actor=resolve_actor(auth, user)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Exception in delete_invitation: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.patch(
    "/agents/{agent_id}/invitations/{invitation_id}",
    response_model=UpdateRoleResponse,
)
async def update_invitation_role(
    agent_id: str = Path(..., description="Agent ID"),
    invitation_id: str = Path(..., description="Invitation ID (invited user's email)"),
    body: UpdateRoleRequest = None,
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("invite")),
):
    """
    Change a collaborator's role

    The role is recorded and reported back, but nothing authorizes on it: `require_agent_permission`
    admits any valid login regardless of role. Treat it as a label the dashboard renders, not as a
    permission boundary.
    """
    try:
        if not body:
            raise HTTPException(status_code=400, detail="role is required")

        return await update_agent_invitation_role(
            agent_id, invitation_id, body.role, actor=resolve_actor(auth, user)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Exception in update_invitation_role: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
