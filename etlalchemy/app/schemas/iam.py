"""HTTP and MCP response models of the IAM context.

The package imports only pydantic, the standard library and the read-model rows,
so both delivery layers share one model set.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from etlalchemy.iam.projection.view import (
    ApiKeyRow,
    AuditRow,
    GroupMemberRow,
    GroupRow,
    IdentityRow,
    MemberRow,
    ProviderRow,
    TenantRow,
    UserRow,
)


class TenantResponse(BaseModel):
    """A tenant."""

    tenant_id: UUID
    name: str
    description: str
    status: str

    @classmethod
    def from_row(cls, row: TenantRow) -> TenantResponse:
        """Builds the response from a read-model row."""
        return cls(
            tenant_id=row.tenant_id,
            name=row.name,
            description=row.description,
            status=row.status,
        )


class MemberResponse(BaseModel):
    """A tenant membership joined with its user."""

    tenant_id: UUID
    user_id: UUID
    username: str
    email: str
    joined_at: datetime
    status: str

    @classmethod
    def from_row(cls, row: MemberRow) -> MemberResponse:
        """Builds the response from a read-model row."""
        return cls(
            tenant_id=row.tenant_id,
            user_id=row.user_id,
            username=row.username,
            email=row.email,
            joined_at=row.joined_at,
            status=row.status,
        )


class UserResponse(BaseModel):
    """A user."""

    user_id: UUID
    username: str
    email: str
    display_name: str
    status: str
    is_system_admin: bool

    @classmethod
    def from_row(cls, row: UserRow) -> UserResponse:
        """Builds the response from a read-model row."""
        return cls(
            user_id=row.user_id,
            username=row.username,
            email=row.email,
            display_name=row.display_name,
            status=row.status,
            is_system_admin=row.is_system_admin,
        )


class UserSummaryResponse(BaseModel):
    """A user reduced to what a mention needs.

    The full user row is administrator-only; this summary answers the ``@``
    autocomplete of any signed-in user without exposing the account state.
    """

    user_id: UUID
    """ID of the user."""
    username: str
    """Login name of the user."""
    display_name: str
    """Name shown in the mention list."""

    @classmethod
    def from_row(cls, row: UserRow) -> UserSummaryResponse:
        """Builds the response from a read-model row."""
        return cls(
            user_id=row.user_id,
            username=row.username,
            display_name=row.display_name or row.username,
        )


class IdentityResponse(BaseModel):
    """A login identity; never carries credential material."""

    identity_id: UUID
    user_id: UUID
    identity_type: str
    provider: str
    display_name: str
    status: str
    credential_version: int
    last_used_at: datetime | None = None

    @classmethod
    def from_row(cls, row: IdentityRow) -> IdentityResponse:
        """Builds the response from a read-model row."""
        return cls(
            identity_id=row.identity_id,
            user_id=row.user_id,
            identity_type=row.identity_type,
            provider=row.provider,
            display_name=row.display_name,
            status=row.status,
            credential_version=row.credential_version,
            last_used_at=row.last_used_at,
        )


class ApiKeyResponse(BaseModel):
    """An API key; never carries the secret or its hash."""

    key_id: UUID
    prefix: str
    scopes: list[str]
    status: str
    created_at: datetime
    expires_at: datetime | None = None
    grace_until: datetime | None = None
    rotated_from: UUID | None = None
    last_used_at: datetime | None = None

    @classmethod
    def from_row(cls, row: ApiKeyRow) -> ApiKeyResponse:
        """Builds the response from a read-model row."""
        return cls(
            key_id=row.key_id,
            prefix=row.prefix,
            scopes=list(row.scopes),
            status=row.status,
            created_at=row.created_at,
            expires_at=row.expires_at,
            grace_until=row.grace_until,
            rotated_from=row.rotated_from,
            last_used_at=row.last_used_at,
        )


class ApiKeySecretResponse(BaseModel):
    """A new API key secret, returned exactly once."""

    key_id: UUID
    secret: str


class SessionResponse(BaseModel):
    """A reference to a session, including the bearer token that addresses it."""

    access_token: str
    token_type: str = "bearer"
    session_id: UUID
    identity_id: UUID
    user_id: UUID
    tenant_id: UUID | None = None
    expires_at: datetime
    refresh_at: datetime
    """Moment at which the client should refresh the token, before ``expires_at``."""


class TokenResponse(BaseModel):
    """Response of the OAuth2 password grant endpoint."""

    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    refresh_at: datetime
    """Moment at which the client should refresh the token, before ``expires_at``."""
    session_id: UUID
    user_id: UUID
    identity_id: UUID
    tenant_id: UUID | None = None


class GroupResponse(BaseModel):
    """A group."""

    group_id: UUID
    tenant_id: UUID
    name: str
    description: str
    parent_group_id: UUID | None = None

    @classmethod
    def from_row(cls, row: GroupRow) -> GroupResponse:
        """Builds the response from a read-model row."""
        return cls(
            group_id=row.group_id,
            tenant_id=row.tenant_id,
            name=row.name,
            description=row.description,
            parent_group_id=row.parent_group_id,
        )


class GroupMemberResponse(BaseModel):
    """One member of a group."""

    group_id: UUID
    member_id: UUID
    member_kind: str
    added_at: datetime

    @classmethod
    def from_row(cls, row: GroupMemberRow) -> GroupMemberResponse:
        """Builds the response from a read-model row."""
        return cls(
            group_id=row.group_id,
            member_id=row.member_id,
            member_kind=row.member_kind,
            added_at=row.added_at,
        )


class ProviderResponse(BaseModel):
    """An auth provider, with the secret reference reduced to a flag."""

    provider_id: UUID
    provider_key: str
    kind: str
    display_name: str
    tenant_id: UUID | None = None
    status: str
    has_secret: bool
    config: dict[str, str] = Field(default_factory=dict)

    @classmethod
    def from_row(cls, row: ProviderRow) -> ProviderResponse:
        """Builds the response from a read-model row, hiding the secret reference."""
        secret_ref = row.config.get("client_secret_ref", "")
        public = {key: value for key, value in row.config.items() if key != "client_secret_ref"}
        return cls(
            provider_id=row.provider_id,
            provider_key=row.provider_key,
            kind=row.kind,
            display_name=row.display_name,
            tenant_id=row.tenant_id,
            status=row.status,
            has_secret=bool(secret_ref),
            config=public,
        )


class AuditResponse(BaseModel):
    """One audit record."""

    audit_id: int
    occurred_at: datetime
    actor_user_id: UUID | None = None
    actor_identity_id: UUID | None = None
    action: str
    target_type: str
    target_id: str
    tenant_id: UUID | None = None
    result: str
    detail: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_row(cls, row: AuditRow) -> AuditResponse:
        """Builds the response from a read-model row."""
        return cls(
            audit_id=row.audit_id,
            occurred_at=row.occurred_at,
            actor_user_id=row.actor_user_id,
            actor_identity_id=row.actor_identity_id,
            action=row.action,
            target_type=row.target_type,
            target_id=row.target_id,
            tenant_id=row.tenant_id,
            result=row.result,
            detail=dict(row.detail),
        )


class AuthorizeResponse(BaseModel):
    """The outcome of one authorization check."""

    allowed: bool


class BootstrapStatusResponse(BaseModel):
    """Whether the system already has a system administrator."""

    completed: bool


class TenantCreatedResponse(BaseModel):
    """The id of a newly created tenant."""

    tenant_id: UUID


class UserCreatedResponse(BaseModel):
    """The id of a newly created user."""

    user_id: UUID


class IdentityCreatedResponse(BaseModel):
    """The id of a newly created identity."""

    identity_id: UUID


class GroupCreatedResponse(BaseModel):
    """The id of a newly created group."""

    group_id: UUID


class ProviderCreatedResponse(BaseModel):
    """The id of a newly created auth provider."""

    provider_id: UUID


__all__ = [
    "ApiKeyResponse",
    "ApiKeySecretResponse",
    "AuditResponse",
    "AuthorizeResponse",
    "BootstrapStatusResponse",
    "GroupCreatedResponse",
    "GroupMemberResponse",
    "GroupResponse",
    "IdentityCreatedResponse",
    "IdentityResponse",
    "MemberResponse",
    "ProviderCreatedResponse",
    "ProviderResponse",
    "SessionResponse",
    "TenantCreatedResponse",
    "TenantResponse",
    "UserCreatedResponse",
    "UserResponse",
]
