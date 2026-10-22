"""
Pydantic schemas for API v1 endpoints

This package contains all Pydantic models used for request/response validation
organized by resource type.
"""

# Agent schemas
from .agents import (
    CreateAgentRequest,
    UpdateAgentRequest,
    PatchAgentRequest,
    AgentResponse,
    AgentListResponse,
)

# Configuration schemas
from .config import (
    NodeConfig,
    NodeConfigsRequest,
    AgentParamsRequest,
)

# Database schemas
from .database import (
    DatabaseConnectionResponse,
    DatabaseConnectionRequest,
    TestDatabaseConnectionRequest,
)

# Table schemas
from .tables import (
    TableDescriptionItem,
    BulkTableDescriptionsRequest,
    TableVisibilityItem,
    BulkTableVisibilityRequest,
    SingleTableVisibilityRequest,
    SingleTableUpdateRequest,
    HighCardinalityColumnItem,
    HighCardinalityColumnsRequest,
)

# Column schemas
from .columns import (
    ColumnInfo,
    ColumnDescriptionUpdate,
    BulkColumnDescriptionsRequest,
    SingleColumnDescriptionRequest,
)

# Few-shot schemas
from .fewshot import (
    FewShotExampleItem,
    BulkFewShotExamplesRequest,
)

# Chat schemas
from .chat import (
    ChatRequest,
    SessionMessageRequest,
    MessageHistoryResponse,
)

# Feedback schemas
from .feedback import (
    FeedbackRequest,
)

# Invitation schemas
from .invitations import (
    InvitationItem,
    InviteUsersRequest,
    InvitedUser,
    CreateInvitationsResponse,
    InvitationsListResponse,
    RemoveInvitationRequest,
    DeleteInvitationResponse,
    UpdateRoleRequest,
    UpdateRoleResponse,
)


# Session schemas
from .sessions import (
    SessionResponse,
    SessionListResponse,
    SessionDetailResponse,
    UpdateSessionRequest,
)

__all__ = [
    # Agents
    "CreateAgentRequest",
    "UpdateAgentRequest",
    "PatchAgentRequest",
    "AgentResponse",
    "AgentListResponse",
    # Config
    "NodeConfig",
    "NodeConfigsRequest",
    "AgentParamsRequest",
    # Database
    "DatabaseConnectionResponse",
    "DatabaseConnectionRequest",
    "TestDatabaseConnectionRequest",
    # Tables
    "TableDescriptionItem",
    "BulkTableDescriptionsRequest",
    "TableVisibilityItem",
    "BulkTableVisibilityRequest",
    "SingleTableVisibilityRequest",
    "SingleTableUpdateRequest",
    "HighCardinalityColumnItem",
    "HighCardinalityColumnsRequest",
    # Columns
    "ColumnInfo",
    "ColumnDescriptionUpdate",
    "BulkColumnDescriptionsRequest",
    "SingleColumnDescriptionRequest",
    # Few-shot
    "FewShotExampleItem",
    "BulkFewShotExamplesRequest",
    # Chat
    "ChatRequest",
    "SessionMessageRequest",
    "MessageHistoryResponse",
    # Feedback
    "FeedbackRequest",
    # Invitations
    "InvitationItem",
    "InviteUsersRequest",
    "InvitedUser",
    "CreateInvitationsResponse",
    "InvitationsListResponse",
    "RemoveInvitationRequest",
    "DeleteInvitationResponse",
    "UpdateRoleRequest",
    "UpdateRoleResponse",
    # Sessions
    "SessionResponse",
    "SessionListResponse",
    "SessionDetailResponse",
    "UpdateSessionRequest",
]

