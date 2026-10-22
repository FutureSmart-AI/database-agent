"""
Pydantic schemas for Invitations endpoints

The request and response shapes deliberately match the chat service's, so the dashboard's Share
screen can be repointed at NL2SQL without a frontend change. Two intentional differences, both
additive:

- `failed_emails` stays a list of plain addresses as the chat service returns it, and a parallel
  `failures` list carries the reason for each. A client reading only `failed_emails` is unaffected.
- The listing returns `invited_by` and `updated_at` alongside the fields the chat service sends.
"""
from typing import List, Optional

from pydantic import BaseModel, Field, model_validator


class InvitationItem(BaseModel):
    """One person being invited, at one role."""
    email: str = Field(..., description="Email address to invite")
    role: Optional[str] = Field(
        "viewer",
        description="Role to grant: 'viewer' (chat only) or 'editor' (everything but the database credentials)",
    )


class InviteUsersRequest(BaseModel):
    """Request model for inviting users.

    Accepts either `invitations` (email + role, as the Share screen sends) or the older bare
    `emails` list, which is treated as a list of viewers. Supplying both merges them, with
    `invitations` winning on any address that appears in each.
    """
    owner_email: Optional[str] = Field(
        None,
        description="Ignored. Who grants access is taken from the authenticated caller and the agent's owner.",
    )
    invitations: Optional[List[InvitationItem]] = Field(
        None, description="Users to invite, each with a role"
    )
    emails: Optional[List[str]] = Field(
        None, description="Legacy form: bare addresses, each invited as 'viewer'"
    )

    @model_validator(mode="before")
    @classmethod
    def strip_owner_email_from_payload(cls, values):
        """Drop a client-supplied owner_email so a caller cannot record the invitation as
        somebody else's grant. The field stays declared so existing payloads still validate."""
        if isinstance(values, dict):
            values.pop("owner_email", None)
        return values

    def resolved_invitations(self) -> List[dict]:
        """The two accepted forms flattened into one `[{email, role}]` list."""
        merged: dict = {}
        for email in self.emails or []:
            if email and email.strip():
                merged[email.strip().lower()] = {"email": email, "role": "viewer"}
        for item in self.invitations or []:
            if item.email and item.email.strip():
                merged[item.email.strip().lower()] = {"email": item.email, "role": item.role}
        return list(merged.values())

    class Config:
        json_schema_extra = {
            "example": {
                "invitations": [
                    {"email": "user1@example.com", "role": "editor"},
                    {"email": "user2@example.com", "role": "viewer"},
                ]
            }
        }


class InvitedUser(BaseModel):
    """One collaborator, as returned by the create and list endpoints."""
    email: str
    role: str
    invited_by: Optional[str] = None
    invited_at: Optional[str] = None
    updated_at: Optional[str] = None


class FailedInvitation(BaseModel):
    """One address that could not be invited, and why."""
    email: Optional[str] = None
    reason: str


class CreateInvitationsResponse(BaseModel):
    """Response model for inviting users"""
    message: str
    invited_users: List[InvitedUser]
    failed_emails: List[Optional[str]] = Field(
        default_factory=list, description="Addresses that failed, for clients expecting the chat service shape"
    )
    failures: List[FailedInvitation] = Field(
        default_factory=list, description="The same failures, each with a reason"
    )


class InvitationsListResponse(BaseModel):
    """Response model for listing an agent's collaborators"""
    invited_users: List[InvitedUser]


class RemoveInvitationRequest(BaseModel):
    """Request model for removing an invitation. The body is optional — the address is in the path."""
    owner_email: Optional[str] = Field(None, description="Ignored, as on the invite request")

    @model_validator(mode="before")
    @classmethod
    def strip_owner_email_from_payload(cls, values):
        if isinstance(values, dict):
            values.pop("owner_email", None)
        return values


class DeleteInvitationResponse(BaseModel):
    """Response model for removing an invitation"""
    message: str


class UpdateRoleRequest(BaseModel):
    """Request model for changing a collaborator's role"""
    owner_email: Optional[str] = Field(None, description="Ignored, as on the invite request")
    role: str = Field(..., description="New role: 'viewer' or 'editor'")

    @model_validator(mode="before")
    @classmethod
    def strip_owner_email_from_payload(cls, values):
        if isinstance(values, dict):
            values.pop("owner_email", None)
        return values

    class Config:
        json_schema_extra = {"example": {"role": "editor"}}


class UpdateRoleResponse(BaseModel):
    """Response model for changing a collaborator's role"""
    message: str
    email: str
    role: str
    previous_role: Optional[str] = None
