"""Read model interface of the IAM context.

The view is the only place the IAM use cases read from. It also owns the Casbin
rule table, which the authorizer loads into an in-memory enforcer.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from eventsourcing.asyncio.persistence import AsyncTrackingRecorder
from eventsourcing.persistence import Tracking


def as_uuid(value: UUID | str) -> UUID:
    """Returns the given value as a :class:`UUID`."""
    return value if isinstance(value, UUID) else UUID(value)


@dataclass(frozen=True)
class AuditEntry:
    """One audit record written together with the event it describes."""

    occurred_at: datetime
    action: str
    target_type: str
    target_id: str
    result: str = "ok"
    actor_user_id: UUID | None = None
    actor_identity_id: UUID | None = None
    tenant_id: UUID | None = None
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TenantRow:
    """A tenant as stored in the read model."""

    tenant_id: UUID
    name: str
    description: str
    status: str


@dataclass(frozen=True)
class MemberRow:
    """A tenant membership joined with the user it belongs to."""

    tenant_id: UUID
    user_id: UUID
    username: str
    email: str
    joined_at: datetime
    status: str


@dataclass(frozen=True)
class UserRow:
    """A user as stored in the read model."""

    user_id: UUID
    username: str
    email: str
    display_name: str
    status: str
    is_system_admin: bool


@dataclass(frozen=True)
class IdentityRow:
    """A login identity as stored in the read model."""

    identity_id: UUID
    user_id: UUID
    identity_type: str
    provider: str
    display_name: str
    status: str
    credential_version: int
    provider_id: UUID | None
    oidc_issuer: str | None
    oidc_subject: str | None
    last_used_at: datetime | None


@dataclass(frozen=True)
class ApiKeyRow:
    """One API key as stored in the read model."""

    key_id: UUID
    identity_id: UUID
    user_id: UUID
    prefix: str
    secret_hash: str
    """Hash of the key secret; never rendered by a delivery layer."""
    scopes: list[str]
    status: str
    created_at: datetime
    expires_at: datetime | None
    grace_until: datetime | None
    revoked_at: datetime | None
    rotated_from: UUID | None
    last_used_at: datetime | None


@dataclass(frozen=True)
class SessionRow:
    """One login session as stored in the read model."""

    session_id: UUID
    identity_id: UUID
    user_id: UUID
    tenant_id: UUID | None
    identity_type: str
    api_key_id: UUID | None
    credential_version: int
    status: str
    created_at: datetime
    expires_at: datetime
    last_seen_at: datetime
    revoked_reason: str | None


@dataclass(frozen=True)
class GroupRow:
    """A group as stored in the read model."""

    group_id: UUID
    tenant_id: UUID
    name: str
    description: str
    parent_group_id: UUID | None


@dataclass(frozen=True)
class GroupMemberRow:
    """One member of a group."""

    group_id: UUID
    member_id: UUID
    member_kind: str
    added_at: datetime


@dataclass(frozen=True)
class PermissionGrantRow:
    """One permission granted to a group."""

    group_id: UUID
    tenant_id: UUID
    obj: str
    act: str


@dataclass(frozen=True)
class ProviderRow:
    """An auth provider as stored in the read model."""

    provider_id: UUID
    provider_key: str
    kind: str
    display_name: str
    tenant_id: UUID | None
    config: dict[str, str]
    status: str


@dataclass(frozen=True)
class CasbinRuleRow:
    """One Casbin ``p`` or ``g`` rule."""

    ptype: str
    v0: str
    v1: str
    v2: str
    v3: str = ""


@dataclass(frozen=True)
class AuditRow:
    """One audit record."""

    audit_id: int
    occurred_at: datetime
    actor_user_id: UUID | None
    actor_identity_id: UUID | None
    action: str
    target_type: str
    target_id: str
    tenant_id: UUID | None
    result: str
    detail: dict[str, Any]


class IamView(AsyncTrackingRecorder, ABC):
    """Read model of the IAM context.

    Every write method receives the :class:`Tracking` object of the event it
    applies and must write the view change and the tracking record in the same
    database transaction.
    """

    @abstractmethod
    async def create_table(self) -> None:
        """Creates the tracking table and the view tables if they do not exist."""
        ...

    @abstractmethod
    def policy_generation(self) -> int:
        """Returns a counter that changes whenever a Casbin rule is written."""
        ...

    # -- tenants ------------------------------------------------------------

    @abstractmethod
    async def register_tenant(
        self,
        tenant_id: UUID,
        name: str,
        description: str,
        status: str,
        tracking: Tracking,
        audit: AuditEntry | None = None,
    ) -> None:
        """Registers a tenant, clearing a previous discarded marker."""
        ...

    @abstractmethod
    async def change_tenant(
        self,
        tenant_id: UUID,
        name: str | None,
        description: str | None,
        status: str | None,
        tracking: Tracking,
        audit: AuditEntry | None = None,
    ) -> None:
        """Changes a tenant, updating only the non-``None`` attributes."""
        ...

    @abstractmethod
    async def discard_tenant(
        self,
        tenant_id: UUID,
        tracking: Tracking,
        audit: AuditEntry | None = None,
    ) -> None:
        """Marks a tenant as discarded."""
        ...

    @abstractmethod
    async def get_tenant(self, tenant_id: UUID) -> TenantRow | None:
        """Returns one live tenant, or ``None``."""
        ...

    @abstractmethod
    async def find_tenant_by_name(self, name: str) -> TenantRow | None:
        """Returns the live tenant with the given name, or ``None``."""
        ...

    @abstractmethod
    async def list_tenants(self) -> list[TenantRow]:
        """Returns every live tenant, ordered by name."""
        ...

    # -- tenant members -----------------------------------------------------

    @abstractmethod
    async def register_member(
        self,
        tenant_id: UUID,
        user_id: UUID,
        joined_at: datetime,
        status: str,
        tracking: Tracking,
    ) -> None:
        """Registers a tenant membership."""
        ...

    @abstractmethod
    async def remove_member(self, tenant_id: UUID, user_id: UUID, tracking: Tracking) -> None:
        """Removes a membership, its ``g`` rules and the sessions of that tenant."""
        ...

    @abstractmethod
    async def change_member_status(
        self,
        tenant_id: UUID,
        user_id: UUID,
        status: str,
        tracking: Tracking,
    ) -> None:
        """Changes the status of one tenant membership."""
        ...

    @abstractmethod
    async def get_membership(self, tenant_id: UUID, user_id: UUID) -> MemberRow | None:
        """Returns one membership joined with its user, or ``None``."""
        ...

    @abstractmethod
    async def list_members(self, tenant_id: UUID) -> list[MemberRow]:
        """Returns the members of a tenant, ordered by username."""
        ...

    @abstractmethod
    async def list_memberships(self, user_id: UUID) -> list[MemberRow]:
        """Returns the live memberships of a user."""
        ...

    # -- users --------------------------------------------------------------

    @abstractmethod
    async def register_user(
        self,
        user_id: UUID,
        username: str,
        email: str,
        display_name: str,
        status: str,
        tracking: Tracking,
    ) -> None:
        """Registers a user, clearing a previous discarded marker."""
        ...

    @abstractmethod
    async def change_user(
        self,
        user_id: UUID,
        username: str | None,
        email: str | None,
        display_name: str | None,
        status: str | None,
        tracking: Tracking,
    ) -> None:
        """Changes a user, updating only the non-``None`` attributes.

        A ``SUSPENDED`` status also revokes every active session of the user.
        """
        ...

    @abstractmethod
    async def set_system_admin(
        self,
        user_id: UUID,
        is_system_admin: bool,
        tracking: Tracking,
        audit: AuditEntry | None = None,
    ) -> None:
        """Sets the system administrator flag of a user."""
        ...

    @abstractmethod
    async def discard_user(self, user_id: UUID, tracking: Tracking) -> None:
        """Marks a user as discarded."""
        ...

    @abstractmethod
    async def get_user(self, user_id: UUID) -> UserRow | None:
        """Returns one live user, or ``None``."""
        ...

    @abstractmethod
    async def find_user_by_login(self, login: str) -> UserRow | None:
        """Returns the live user whose username or email matches ``login``."""
        ...

    @abstractmethod
    async def list_users(self) -> list[UserRow]:
        """Returns every live user, ordered by username."""

    @abstractmethod
    async def search_users(self, term: str, limit: int = 8) -> list[UserRow]:
        """Returns the live users whose name, username or email contains ``term``."""
        ...

    @abstractmethod
    async def count_system_admins(self) -> int:
        """Returns the number of live system administrators."""
        ...

    @abstractmethod
    async def list_system_admins(self) -> list[UserRow]:
        """Returns the live system administrators, ordered by username."""
        ...

    # -- identities ---------------------------------------------------------

    @abstractmethod
    async def register_identity(
        self,
        identity_id: UUID,
        user_id: UUID,
        identity_type: str,
        provider: str,
        display_name: str,
        status: str,
        tracking: Tracking,
    ) -> None:
        """Registers an identity, clearing a previous discarded marker."""
        ...

    @abstractmethod
    async def change_identity(
        self,
        identity_id: UUID,
        display_name: str | None,
        status: str | None,
        tracking: Tracking,
    ) -> None:
        """Changes an identity; ``DISABLED`` revokes the sessions it issued."""
        ...

    @abstractmethod
    async def set_password(
        self,
        identity_id: UUID,
        password_hash: str,
        credential_version: int,
        updated_at: datetime,
        tracking: Tracking,
        audit: AuditEntry | None = None,
    ) -> None:
        """Stores the password hash and the new credential version."""
        ...

    @abstractmethod
    async def set_oidc_subject(
        self,
        identity_id: UUID,
        provider_id: UUID,
        issuer: str,
        subject: str,
        credential_version: int,
        tracking: Tracking,
        audit: AuditEntry | None = None,
    ) -> None:
        """Stores the OIDC binding and the new credential version."""
        ...

    @abstractmethod
    async def discard_identity(
        self,
        identity_id: UUID,
        tracking: Tracking,
        audit: AuditEntry | None = None,
    ) -> None:
        """Marks an identity as discarded and revokes its API keys."""
        ...

    @abstractmethod
    async def get_identity(self, identity_id: UUID) -> IdentityRow | None:
        """Returns one live identity, or ``None``."""
        ...

    @abstractmethod
    async def list_identities(self, user_id: UUID) -> list[IdentityRow]:
        """Returns the live identities of a user."""
        ...

    @abstractmethod
    async def find_password_identity(self, login: str) -> IdentityRow | None:
        """Returns the password identity of the user matching ``login``."""
        ...

    @abstractmethod
    async def find_oidc_identity(self, issuer: str, subject: str) -> IdentityRow | None:
        """Returns the OIDC identity bound to an issuer and subject."""
        ...

    @abstractmethod
    async def get_password_hash(self, identity_id: UUID) -> str | None:
        """Returns the password hash of an identity, or ``None``."""
        ...

    @abstractmethod
    async def count_provider_identities(self, provider_id: UUID) -> int:
        """Returns the number of live identities bound to a provider."""
        ...

    # -- API keys -----------------------------------------------------------

    @abstractmethod
    async def register_api_key(
        self,
        key_id: UUID,
        identity_id: UUID,
        user_id: UUID,
        prefix: str,
        secret_hash: str,
        scopes: list[str],
        created_at: datetime,
        expires_at: datetime | None,
        rotated_from: UUID | None,
        tracking: Tracking,
        audit: AuditEntry | None = None,
    ) -> None:
        """Registers an API key."""
        ...

    @abstractmethod
    async def rotate_api_key(
        self,
        old_key_id: UUID,
        new_key_id: UUID,
        identity_id: UUID,
        user_id: UUID,
        prefix: str,
        secret_hash: str,
        scopes: list[str],
        created_at: datetime,
        expires_at: datetime | None,
        grace_until: datetime,
        tracking: Tracking,
        audit: AuditEntry | None = None,
    ) -> None:
        """Moves the old key to ``GRACE``, inserts the new key, revokes old sessions."""
        ...

    @abstractmethod
    async def revoke_api_key(
        self,
        key_id: UUID,
        revoked_at: datetime,
        tracking: Tracking,
        audit: AuditEntry | None = None,
    ) -> None:
        """Revokes an API key and the sessions it issued."""
        ...

    @abstractmethod
    async def list_api_keys(self, user_id: UUID) -> list[ApiKeyRow]:
        """Returns the API keys of a user, newest first."""
        ...

    @abstractmethod
    async def get_api_key(self, key_id: UUID) -> ApiKeyRow | None:
        """Returns one API key, or ``None``."""
        ...

    @abstractmethod
    async def find_api_keys_by_prefix(self, prefix: str) -> list[ApiKeyRow]:
        """Returns the API keys that start with the given prefix."""
        ...

    # -- sessions -----------------------------------------------------------

    @abstractmethod
    async def register_session(
        self,
        session_id: UUID,
        identity_id: UUID,
        user_id: UUID,
        tenant_id: UUID | None,
        identity_type: str,
        api_key_id: UUID | None,
        credential_version: int,
        created_at: datetime,
        expires_at: datetime,
        tracking: Tracking,
    ) -> None:
        """Registers a session."""
        ...

    @abstractmethod
    async def refresh_session(
        self,
        session_id: UUID,
        expires_at: datetime,
        last_seen_at: datetime,
        tracking: Tracking,
    ) -> None:
        """Updates the expiry and the last use of a session."""
        ...

    @abstractmethod
    async def revoke_session(
        self,
        session_id: UUID,
        reason: str,
        tracking: Tracking,
        audit: AuditEntry | None = None,
    ) -> None:
        """Marks one session as revoked."""
        ...

    @abstractmethod
    async def revoke_sessions_for_identity(
        self,
        identity_id: UUID,
        reason: str,
        tracking: Tracking,
    ) -> None:
        """Revokes every active session of an identity."""
        ...

    @abstractmethod
    async def revoke_sessions_before_credential_version(
        self,
        identity_id: UUID,
        credential_version: int,
        reason: str,
        tracking: Tracking,
    ) -> None:
        """Revokes the sessions of an identity below a credential version."""
        ...

    @abstractmethod
    async def revoke_sessions_for_api_key(
        self,
        api_key_id: UUID,
        reason: str,
        tracking: Tracking,
    ) -> None:
        """Revokes every active session issued by an API key."""
        ...

    @abstractmethod
    async def revoke_sessions_for_user(
        self,
        user_id: UUID,
        reason: str,
        tracking: Tracking,
    ) -> None:
        """Revokes every active session of a user."""
        ...

    @abstractmethod
    async def revoke_sessions_for_user_tenant(
        self,
        user_id: UUID,
        tenant_id: UUID,
        reason: str,
        tracking: Tracking,
    ) -> None:
        """Revokes the active sessions of a user in one tenant."""
        ...

    @abstractmethod
    async def revoke_sessions_for_tenant(
        self,
        tenant_id: UUID,
        reason: str,
        tracking: Tracking,
    ) -> None:
        """Revokes every active session that acts in a tenant."""
        ...

    @abstractmethod
    async def get_session(self, session_id: UUID) -> SessionRow | None:
        """Returns one session, or ``None``."""
        ...

    # -- groups -------------------------------------------------------------

    @abstractmethod
    async def register_group(
        self,
        group_id: UUID,
        tenant_id: UUID,
        name: str,
        description: str,
        parent_group_id: UUID | None,
        tracking: Tracking,
    ) -> None:
        """Registers a group, clearing a previous discarded marker."""
        ...

    @abstractmethod
    async def change_group(
        self,
        group_id: UUID,
        name: str | None,
        description: str | None,
        tracking: Tracking,
    ) -> None:
        """Changes a group, updating only the non-``None`` attributes."""
        ...

    @abstractmethod
    async def change_group_parent(
        self,
        group_id: UUID,
        parent_group_id: UUID | None,
        tracking: Tracking,
    ) -> None:
        """Updates the parent of a group and drops its own ``g`` edge."""
        ...

    @abstractmethod
    async def discard_groups(
        self,
        group_ids: list[UUID],
        tracking: Tracking,
    ) -> None:
        """Marks the given groups as discarded."""
        ...

    @abstractmethod
    async def get_group(self, group_id: UUID) -> GroupRow | None:
        """Returns one live group, or ``None``."""
        ...

    @abstractmethod
    async def find_group_by_name(
        self,
        tenant_id: UUID,
        parent_group_id: UUID | None,
        name: str,
    ) -> GroupRow | None:
        """Returns the live sibling group with the given name, or ``None``."""
        ...

    @abstractmethod
    async def list_groups(self, tenant_id: UUID) -> list[GroupRow]:
        """Returns the live groups of a tenant, ordered by name."""
        ...

    @abstractmethod
    async def add_group_member(
        self,
        group_id: UUID,
        member_id: UUID,
        member_kind: str,
        tenant_id: UUID,
        added_at: datetime,
        tracking: Tracking,
    ) -> None:
        """Adds a member to a group and writes its ``g`` rule."""
        ...

    @abstractmethod
    async def remove_group_member(
        self,
        group_id: UUID,
        member_id: UUID,
        member_kind: str,
        tracking: Tracking,
    ) -> None:
        """Removes a member from a group and deletes its ``g`` rule."""
        ...

    @abstractmethod
    async def list_group_members(self, tenant_id: UUID) -> list[GroupMemberRow]:
        """Returns every group membership of a tenant."""
        ...

    @abstractmethod
    async def grant_permission(
        self,
        group_id: UUID,
        tenant_id: UUID,
        obj: str,
        act: str,
        tracking: Tracking,
    ) -> None:
        """Registers a permission grant and writes its ``p`` rule."""
        ...

    @abstractmethod
    async def revoke_permission(
        self,
        group_id: UUID,
        tenant_id: UUID,
        obj: str,
        act: str,
        tracking: Tracking,
    ) -> None:
        """Removes a permission grant and deletes its ``p`` rule."""
        ...

    @abstractmethod
    async def list_permission_grants(self, tenant_id: UUID) -> list[PermissionGrantRow]:
        """Returns the permission grants of a tenant."""
        ...

    # -- auth providers -----------------------------------------------------

    @abstractmethod
    async def register_provider(
        self,
        provider_id: UUID,
        provider_key: str,
        kind: str,
        display_name: str,
        tenant_id: UUID | None,
        config: dict[str, str],
        status: str,
        tracking: Tracking,
        audit: AuditEntry | None = None,
    ) -> None:
        """Registers an auth provider, clearing a previous discarded marker."""
        ...

    @abstractmethod
    async def change_provider(
        self,
        provider_id: UUID,
        display_name: str | None,
        status: str | None,
        tracking: Tracking,
        audit: AuditEntry | None = None,
    ) -> None:
        """Changes a provider, updating only the non-``None`` attributes."""
        ...

    @abstractmethod
    async def update_provider_config(
        self,
        provider_id: UUID,
        config: dict[str, str],
        tracking: Tracking,
        audit: AuditEntry | None = None,
    ) -> None:
        """Replaces the configuration of a provider."""
        ...

    @abstractmethod
    async def discard_provider(
        self,
        provider_id: UUID,
        tracking: Tracking,
        audit: AuditEntry | None = None,
    ) -> None:
        """Marks a provider as discarded."""
        ...

    @abstractmethod
    async def get_provider(self, provider_id: UUID) -> ProviderRow | None:
        """Returns one live provider, or ``None``."""
        ...

    @abstractmethod
    async def find_provider_by_key(self, provider_key: str) -> ProviderRow | None:
        """Returns the live provider with the given key, or ``None``."""
        ...

    @abstractmethod
    async def list_providers(self) -> list[ProviderRow]:
        """Returns every live provider, ordered by key."""
        ...

    # -- casbin -------------------------------------------------------------

    @abstractmethod
    async def add_casbin_rules(
        self,
        rules: list[CasbinRuleRow],
        tracking: Tracking,
    ) -> None:
        """Inserts Casbin rules, ignoring rules that already exist."""
        ...

    @abstractmethod
    async def remove_casbin_rules(
        self,
        rules: list[CasbinRuleRow],
        tracking: Tracking,
    ) -> None:
        """Deletes the given Casbin rules."""
        ...

    @abstractmethod
    async def remove_casbin_rules_for_groups(
        self,
        group_ids: list[UUID],
        tracking: Tracking,
    ) -> None:
        """Deletes every ``p``/``g`` rule that mentions one of the groups."""
        ...

    @abstractmethod
    async def remove_casbin_rules_for_subject(
        self,
        subject: UUID,
        tenant_id: UUID | None,
        tracking: Tracking,
    ) -> None:
        """Deletes the ``g`` rules of a user, optionally in one tenant."""
        ...

    @abstractmethod
    async def list_casbin_rules(self) -> list[CasbinRuleRow]:
        """Returns every Casbin rule."""
        ...

    # -- audit --------------------------------------------------------------

    @abstractmethod
    async def add_audit(
        self,
        entry: AuditEntry,
        tracking: Tracking,
    ) -> None:
        """Appends one standalone audit record."""
        ...

    @abstractmethod
    async def list_audit_events(
        self,
        limit: int = 50,
        offset: int = 0,
        action: str | None = None,
        actor_user_id: UUID | None = None,
    ) -> list[AuditRow]:
        """Returns audit records, newest first."""
        ...
