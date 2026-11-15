"""Tenant aggregate: an organisation boundary and its member bookkeeping."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from eventsourcing.domain import Aggregate, AggregateCreated, event

from etlalchemy.iam.aggregates.errors import (
    DiscardedError,
    DuplicateMembershipError,
    UnknownMembershipError,
)
from etlalchemy.iam.aggregates.types import (
    Membership,
    TenantStatus,
    ensure_member_status,
    ensure_tenant_status,
    validate_name,
)


class Tenant(Aggregate):
    """Aggregate root for a tenant and the users that belong to it.

    Users are separate aggregates, so the tenant keeps one
    :class:`~etlalchemy.iam.aggregates.types.Membership` per user id. The user
    keeps the dual reference; the application writes both in one unit of work.
    """

    def __init__(self, name: str, description: str = "") -> None:
        """Initialises an active tenant with no members."""
        validate_name(name, "tenant")
        self.name = name
        self.description = description
        self.status: TenantStatus = "ACTIVE"
        self.members: dict[UUID, Membership] = {}
        self._is_discarded = False

    class Event(Aggregate.Event):
        """Base class for events raised by the tenant aggregate."""

    @dataclass(frozen=True)
    class Started(AggregateCreated):
        """Recorded when a tenant is created."""

        name: str
        """Name of the new tenant."""
        description: str = ""
        """Free-form description of the new tenant."""

    @dataclass(frozen=True)
    class Changed(Event):
        """Recorded when tenant metadata or status changes."""

        name: str | None = None
        """New name, or ``None`` when unchanged."""
        description: str | None = None
        """New description, or ``None`` when unchanged."""
        status: str | None = None
        """New status, or ``None`` when unchanged."""

    @dataclass(frozen=True)
    class MemberAdded(Event):
        """Recorded when a user joins the tenant."""

        user_id: UUID
        """ID of the joining user."""
        joined_at: datetime
        """Moment the user joined."""
        status: str = "ACTIVE"
        """Initial membership status."""

    @dataclass(frozen=True)
    class MemberRemoved(Event):
        """Recorded when a user leaves the tenant."""

        user_id: UUID
        """ID of the leaving user."""

    @dataclass(frozen=True)
    class MemberStatusChanged(Event):
        """Recorded when a membership is suspended or reactivated."""

        user_id: UUID
        """ID of the affected user."""
        status: str
        """New membership status."""

    @dataclass(frozen=True)
    class Discarded(Event):
        """Recorded when the tenant is discarded."""

    @event(Changed)
    def change(
        self,
        name: str | None = None,
        description: str | None = None,
        status: str | None = None,
    ) -> None:
        """Changes the name, description and/or status of the tenant."""
        self._ensure_not_discarded()
        if name is None and description is None and status is None:
            msg = "change() requires at least one field"
            raise ValueError(msg)
        if name is not None:
            validate_name(name, "tenant")
        checked = None if status is None else ensure_tenant_status(status)
        if name is not None:
            self.name = name
        if description is not None:
            self.description = description
        if checked is not None:
            self.status = checked

    @event(MemberAdded)
    def add_member(
        self,
        user_id: UUID,
        joined_at: datetime,
        status: str = "ACTIVE",
    ) -> None:
        """Adds a user to the tenant."""
        self._ensure_not_discarded()
        if user_id in self.members:
            msg = f"User {user_id} is already a member of tenant {self.name!r}"
            raise DuplicateMembershipError(msg)
        self.members[user_id] = Membership(
            joined_at=joined_at,
            status=ensure_member_status(status),
        )

    @event(MemberRemoved)
    def remove_member(self, user_id: UUID) -> None:
        """Removes a user from the tenant."""
        self._ensure_not_discarded()
        if user_id not in self.members:
            msg = f"User {user_id} is not a member of tenant {self.name!r}"
            raise UnknownMembershipError(msg)
        del self.members[user_id]

    @event(MemberStatusChanged)
    def change_member_status(self, user_id: UUID, status: str) -> None:
        """Changes the status of one membership."""
        self._ensure_not_discarded()
        membership = self.members.get(user_id)
        if membership is None:
            msg = f"User {user_id} is not a member of tenant {self.name!r}"
            raise UnknownMembershipError(msg)
        checked = ensure_member_status(status)
        self.members[user_id] = Membership(
            joined_at=membership.joined_at,
            status=checked,
        )

    @event(Discarded)
    def discard(self) -> None:
        """Marks the tenant as discarded."""
        self._ensure_not_discarded()
        self._is_discarded = True

    def has_member(self, user_id: UUID) -> bool:
        """Returns whether the user is an active member of the tenant."""
        membership = self.members.get(user_id)
        return membership is not None and membership.status == "ACTIVE"

    def _ensure_not_discarded(self) -> None:
        """Raises DiscardedError when the tenant has been discarded."""
        if self._is_discarded:
            msg = "tenant is discarded"
            raise DiscardedError(msg)
