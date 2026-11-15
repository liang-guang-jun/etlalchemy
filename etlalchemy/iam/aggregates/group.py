"""Group aggregate: a tenant-local organisation unit that carries permissions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from eventsourcing.domain import Aggregate, AggregateCreated, event

from etlalchemy.iam.aggregates.errors import (
    DiscardedError,
    DuplicateGroupMemberError,
    DuplicatePermissionGrantError,
    GroupCycleError,
    UnknownGroupMemberError,
    UnknownPermissionGrantError,
)
from etlalchemy.iam.aggregates.types import (
    GroupMember,
    GroupMemberKind,
    Permission,
    ensure_member_kind,
    validate_name,
)


class Group(Aggregate):
    """Aggregate root for a group, its members and its permission grants.

    Groups nest by id. The application walks the ancestor chain before calling
    :meth:`change_parent` or :meth:`add_member` and passes it in, so the aggregate
    can reject a cycle without loading other aggregates.
    """

    def __init__(
        self,
        tenant_id: UUID,
        name: str,
        description: str = "",
        parent_group_id: UUID | None = None,
    ) -> None:
        """Initialises a group in the given tenant."""
        validate_name(name, "group")
        self.tenant_id = tenant_id
        self.name = name
        self.description = description
        self.parent_group_id = parent_group_id
        self.members: dict[UUID, GroupMember] = {}
        self.permission_grants: dict[tuple[str, str], None] = {}
        self._is_discarded = False

    class Event(Aggregate.Event):
        """Base class for events raised by the group aggregate."""

    @dataclass(frozen=True)
    class Started(AggregateCreated):
        """Recorded when a group is created."""

        tenant_id: UUID
        """Tenant that owns the group."""
        name: str
        """Name of the group, unique under its parent."""
        description: str = ""
        """Free-form description of the group."""
        parent_group_id: UUID | None = None
        """Parent group, or ``None`` for a top-level group."""

    @dataclass(frozen=True)
    class Changed(Event):
        """Recorded when the group name or description changes."""

        name: str | None = None
        """New name, or ``None`` when unchanged."""
        description: str | None = None
        """New description, or ``None`` when unchanged."""

    @dataclass(frozen=True)
    class ParentChanged(Event):
        """Recorded when the group is moved below another group."""

        new_parent_id: UUID | None = None
        """New parent, or ``None`` for the top level."""
        ancestors: tuple[UUID, ...] = ()
        """Ancestor chain of the new parent, used to reject a cycle."""

    @dataclass(frozen=True)
    class MemberAdded(Event):
        """Recorded when a user or child group joins the group."""

        member_id: UUID
        """ID of the user or child group."""
        member_kind: str
        """Whether the member is a ``user`` or a ``group``."""
        added_at: datetime
        """Moment the member was added."""
        ancestors: tuple[UUID, ...] = ()
        """Ancestor chain of the group, used to reject a cycle."""

    @dataclass(frozen=True)
    class MemberRemoved(Event):
        """Recorded when a member leaves the group."""

        member_id: UUID
        """ID of the removed user or child group."""
        member_kind: str = "user"
        """Whether the member is a ``user`` or a ``group``."""

    @dataclass(frozen=True)
    class PermissionGranted(Event):
        """Recorded when the group is granted a permission."""

        obj: str
        """Resource identifier."""
        act: str
        """Action identifier."""

    @dataclass(frozen=True)
    class PermissionRevoked(Event):
        """Recorded when a permission is revoked from the group."""

        obj: str
        """Resource identifier."""
        act: str
        """Action identifier."""

    @dataclass(frozen=True)
    class Discarded(Event):
        """Recorded when the group is discarded."""

    @event(Changed)
    def change(self, name: str | None = None, description: str | None = None) -> None:
        """Changes the group name and/or description."""
        self._ensure_not_discarded()
        if name is None and description is None:
            msg = "change() requires at least one field"
            raise ValueError(msg)
        if name is not None:
            validate_name(name, "group")
        if name is not None:
            self.name = name
        if description is not None:
            self.description = description

    @event(ParentChanged)
    def change_parent(
        self,
        new_parent_id: UUID | None = None,
        ancestors: tuple[UUID, ...] = (),
    ) -> None:
        """Moves the group below a new parent, rejecting a cycle."""
        self._ensure_not_discarded()
        if new_parent_id is not None:
            if new_parent_id == self.id:
                msg = "a group cannot be its own parent"
                raise GroupCycleError(msg)
            if new_parent_id in ancestors:
                msg = f"moving group {self.id} below {new_parent_id} creates a cycle"
                raise GroupCycleError(msg)
        self.parent_group_id = new_parent_id

    @event(MemberAdded)
    def add_member(
        self,
        member_id: UUID,
        member_kind: str,
        added_at: datetime,
        ancestors: tuple[UUID, ...] = (),
    ) -> None:
        """Adds a user or child group to the group."""
        self._ensure_not_discarded()
        checked = ensure_member_kind(member_kind)
        if member_id in self.members:
            msg = f"Member {member_id} is already part of group {self.name!r}"
            raise DuplicateGroupMemberError(msg)
        if checked == "group" and (member_id == self.id or member_id in ancestors):
            msg = f"adding group {member_id} creates a cycle"
            raise GroupCycleError(msg)
        self.members[member_id] = GroupMember(kind=checked, added_at=added_at)

    @event(MemberRemoved)
    def _member_removed(self, member_id: UUID, member_kind: str = "user") -> None:
        """Removes a member from the group."""
        self._ensure_not_discarded()
        if member_id not in self.members:
            msg = f"Member {member_id} is not part of group {self.name!r}"
            raise UnknownGroupMemberError(msg)
        del self.members[member_id]

    def remove_member(self, member_id: UUID) -> None:
        """Removes a member, recording its kind in the event."""
        member = self.members.get(member_id)
        if member is None:
            msg = f"Member {member_id} is not part of group {self.name!r}"
            raise UnknownGroupMemberError(msg)
        self._member_removed(member_id, member.kind)

    @event(PermissionGranted)
    def grant_permission(self, obj: str, act: str) -> None:
        """Grants a permission to the group."""
        self._ensure_not_discarded()
        permission = Permission.parse(f"{obj}:{act}")
        key = (permission.resource, permission.action)
        if key in self.permission_grants:
            msg = f"Group {self.name!r} already holds {permission}"
            raise DuplicatePermissionGrantError(msg)
        self.permission_grants[key] = None

    @event(PermissionRevoked)
    def revoke_permission(self, obj: str, act: str) -> None:
        """Revokes a permission from the group."""
        self._ensure_not_discarded()
        permission = Permission.parse(f"{obj}:{act}")
        key = (permission.resource, permission.action)
        if key not in self.permission_grants:
            msg = f"Group {self.name!r} does not hold {permission}"
            raise UnknownPermissionGrantError(msg)
        del self.permission_grants[key]

    @event(Discarded)
    def discard(self) -> None:
        """Marks the group as discarded."""
        self._ensure_not_discarded()
        self._is_discarded = True

    def member_ids(self, kind: GroupMemberKind) -> list[UUID]:
        """Returns the ids of the members of the given kind."""
        return [member_id for member_id, member in self.members.items() if member.kind == kind]

    def _ensure_not_discarded(self) -> None:
        """Raises DiscardedError when the group has been discarded."""
        if self._is_discarded:
            msg = "group is discarded"
            raise DiscardedError(msg)
