"""User aggregate: a natural person and the identities and tenants it owns."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from eventsourcing.domain import Aggregate, AggregateCreated, event

from etlalchemy.iam.aggregates.errors import (
    DiscardedError,
    DuplicateIdentityError,
    IdentityInvariantError,
    UnknownIdentityError,
    UnknownMembershipError,
)
from etlalchemy.iam.aggregates.types import (
    IdentityRef,
    TenantMembership,
    UserStatus,
    ensure_identity_type,
    ensure_user_status,
    validate_name,
)


class User(Aggregate):
    """Aggregate root for a user and the ids of its identities and tenants.

    Identities and tenants are separate aggregates. The user keeps only the
    references needed for authorization and for the deliverable ``User`` shape;
    ids are the only cross-aggregate vocabulary.
    """

    def __init__(self, username: str, email: str, display_name: str = "") -> None:
        """Initialises an active user without identities or memberships."""
        validate_name(username, "user")
        validate_name(email, "user email")
        self.username = username
        self.email = email
        self.display_name = display_name
        self.status: UserStatus = "ACTIVE"
        self.is_system_admin = False
        self.identities: dict[UUID, IdentityRef] = {}
        self.memberships: dict[UUID, TenantMembership] = {}
        self._is_discarded = False

    class Event(Aggregate.Event):
        """Base class for events raised by the user aggregate."""

    @dataclass(frozen=True)
    class Started(AggregateCreated):
        """Recorded when a user is created."""

        username: str
        """Unique, normalised user name."""
        email: str
        """Unique, normalised email address."""
        display_name: str = ""
        """Human readable name."""

    @dataclass(frozen=True)
    class Changed(Event):
        """Recorded when user metadata or status changes."""

        username: str | None = None
        """New username, or ``None`` when unchanged."""
        email: str | None = None
        """New email, or ``None`` when unchanged."""
        display_name: str | None = None
        """New display name, or ``None`` when unchanged."""
        status: str | None = None
        """New status, or ``None`` when unchanged."""

    @dataclass(frozen=True)
    class IdentityAttached(Event):
        """Recorded when an identity is attached to the user."""

        identity_id: UUID
        """ID of the attached identity."""
        identity_type: str
        """Kind of the attached identity."""
        provider: str
        """Provider name of the attached identity."""

    @dataclass(frozen=True)
    class IdentityDetached(Event):
        """Recorded when an identity is detached from the user."""

        identity_id: UUID
        """ID of the detached identity."""

    @dataclass(frozen=True)
    class TenantJoined(Event):
        """Recorded when the user joins a tenant."""

        tenant_id: UUID
        """ID of the tenant."""
        joined_at: datetime
        """Moment the user joined."""

    @dataclass(frozen=True)
    class TenantLeft(Event):
        """Recorded when the user leaves a tenant."""

        tenant_id: UUID
        """ID of the tenant."""

    @dataclass(frozen=True)
    class SystemAdminGranted(Event):
        """Recorded when the user becomes a system administrator."""

        source: str
        """Where the grant came from: ``bootstrap`` or ``admin``."""

    @dataclass(frozen=True)
    class SystemAdminRevoked(Event):
        """Recorded when the system administrator flag is removed."""

    @dataclass(frozen=True)
    class Discarded(Event):
        """Recorded when the user is discarded."""

    @event(Changed)
    def change(
        self,
        username: str | None = None,
        email: str | None = None,
        display_name: str | None = None,
        status: str | None = None,
    ) -> None:
        """Changes user metadata and/or status."""
        self._ensure_not_discarded()
        if username is None and email is None and display_name is None and status is None:
            msg = "change() requires at least one field"
            raise ValueError(msg)
        if username is not None:
            validate_name(username, "user")
        if email is not None:
            validate_name(email, "user email")
        checked = None if status is None else ensure_user_status(status)
        if username is not None:
            self.username = username
        if email is not None:
            self.email = email
        if display_name is not None:
            self.display_name = display_name
        if checked is not None:
            self.status = checked

    @event(IdentityAttached)
    def attach_identity(self, identity_id: UUID, identity_type: str, provider: str) -> None:
        """Attaches an identity reference to the user."""
        self._ensure_not_discarded()
        if identity_id in self.identities:
            msg = f"Identity {identity_id} is already attached to user {self.username!r}"
            raise DuplicateIdentityError(msg)
        self.identities[identity_id] = IdentityRef(
            identity_type=ensure_identity_type(identity_type),
            provider=provider,
        )

    @event(IdentityDetached)
    def detach_identity(self, identity_id: UUID) -> None:
        """Detaches an identity reference from the user."""
        self._ensure_not_discarded()
        if identity_id not in self.identities:
            msg = f"Identity {identity_id} is not attached to user {self.username!r}"
            raise UnknownIdentityError(msg)
        del self.identities[identity_id]

    @event(TenantJoined)
    def join_tenant(self, tenant_id: UUID, joined_at: datetime) -> None:
        """Records that the user joined a tenant."""
        self._ensure_not_discarded()
        self.memberships[tenant_id] = TenantMembership(joined_at=joined_at)

    @event(TenantLeft)
    def leave_tenant(self, tenant_id: UUID) -> None:
        """Records that the user left a tenant."""
        self._ensure_not_discarded()
        if tenant_id not in self.memberships:
            msg = f"User {self.username!r} is not a member of tenant {tenant_id}"
            raise UnknownMembershipError(msg)
        del self.memberships[tenant_id]

    @event(SystemAdminGranted)
    def grant_system_admin(self, source: str) -> None:
        """Grants the system administrator flag.

        The application checks the same invariant first; the aggregate repeats it
        as a second line of defence so an administrator always has a password
        identity to log in with.
        """
        self._ensure_not_discarded()
        if self.is_system_admin:
            return
        if not self.password_identity_ids():
            msg = "a system administrator needs a PASSWORD identity"
            raise IdentityInvariantError(msg)
        self.is_system_admin = True

    @event(SystemAdminRevoked)
    def revoke_system_admin(self) -> None:
        """Removes the system administrator flag."""
        self._ensure_not_discarded()
        if not self.is_system_admin:
            return
        self.is_system_admin = False

    @event(Discarded)
    def discard(self) -> None:
        """Marks the user as discarded."""
        self._ensure_not_discarded()
        self._is_discarded = True

    def password_identity_ids(self) -> list[UUID]:
        """Returns the ids of the password identities of the user."""
        return [
            identity_id
            for identity_id, ref in self.identities.items()
            if ref.identity_type == "PASSWORD"
        ]

    def _ensure_not_discarded(self) -> None:
        """Raises DiscardedError when the user has been discarded."""
        if self._is_discarded:
            msg = "user is discarded"
            raise DiscardedError(msg)
