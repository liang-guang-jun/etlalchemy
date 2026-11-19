"""Tests for the group aggregate."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from etlalchemy.iam.aggregates.errors import (
    DiscardedError,
    DuplicateGroupMemberError,
    DuplicatePermissionGrantError,
    GroupCycleError,
    UnknownGroupMemberError,
    UnknownPermissionGrantError,
)
from etlalchemy.iam.aggregates.group import Group

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def replay(events: list[Any]) -> Group:
    """Rebuilds a group by applying the given events in order."""
    aggregate: Any = None
    for event in events:
        aggregate = event.mutate(aggregate)
    assert isinstance(aggregate, Group)
    return aggregate


def test_started_event_records_the_tenant_and_parent() -> None:
    """A group starts in its tenant, optionally below a parent."""
    tenant_id, parent_id = uuid4(), uuid4()
    group = Group(tenant_id, "analysts", "Analysts", parent_id)

    assert (group.tenant_id, group.parent_group_id) == (tenant_id, parent_id)
    event = group.collect_events()[0]
    assert isinstance(event, Group.Started)
    assert event.tenant_id == tenant_id


def test_moving_below_an_ancestor_is_rejected() -> None:
    """A group cannot become a descendant of itself."""
    group = Group(uuid4(), "child")
    with pytest.raises(GroupCycleError):
        group.change_parent(group.id)

    parent_id = uuid4()
    with pytest.raises(GroupCycleError):
        group.change_parent(parent_id, ancestors=(group.id, parent_id))


def test_adding_a_child_group_that_is_an_ancestor_is_rejected() -> None:
    """A group cannot contain one of its own ancestors."""
    group = Group(uuid4(), "parent")
    ancestor_id = uuid4()
    with pytest.raises(GroupCycleError):
        group.add_member(ancestor_id, "group", NOW, ancestors=(ancestor_id,))

    with pytest.raises(GroupCycleError):
        group.add_member(group.id, "group", NOW)


def test_members_round_trip_through_replay() -> None:
    """Users and child groups are members and survive replay."""
    group = Group(uuid4(), "team")
    user_id, child_id = uuid4(), uuid4()
    group.add_member(user_id, "user", NOW)
    group.add_member(child_id, "group", NOW)

    restored = replay(group.pending_events)
    assert restored.members[user_id].kind == "user"
    assert restored.members[child_id].kind == "group"
    assert restored.member_ids("group") == [child_id]

    with pytest.raises(DuplicateGroupMemberError):
        group.add_member(user_id, "user", NOW)

    group.remove_member(user_id)
    assert replay(group.pending_events).member_ids("user") == []
    with pytest.raises(UnknownGroupMemberError):
        group.remove_member(user_id)


def test_permissions_are_granted_once_and_revoked() -> None:
    """A grant is unique per (obj, act) and replayable."""
    group = Group(uuid4(), "team")
    group.grant_permission("doc:readme", "read")
    assert ("doc:readme", "read") in group.permission_grants
    assert replay(group.collect_events()).permission_grants == group.permission_grants

    with pytest.raises(DuplicatePermissionGrantError):
        group.grant_permission("doc:readme", "read")

    group.revoke_permission("doc:readme", "read")
    assert group.permission_grants == {}
    with pytest.raises(UnknownPermissionGrantError):
        group.revoke_permission("doc:readme", "read")


def test_discarded_group_rejects_every_command() -> None:
    """A discarded group refuses changes, members and grants."""
    group = Group(uuid4(), "team")
    group.discard()

    with pytest.raises(DiscardedError):
        group.change(name="other")
    with pytest.raises(DiscardedError):
        group.add_member(uuid4(), "user", NOW)
    with pytest.raises(DiscardedError):
        group.grant_permission("doc", "read")
    with pytest.raises(DiscardedError):
        group.discard()
