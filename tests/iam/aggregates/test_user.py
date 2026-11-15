"""Tests for the user aggregate."""

from typing import Any
from uuid import uuid4

import pytest

from etlalchemy.iam.aggregates.errors import (
    DiscardedError,
    DuplicateIdentityError,
    IdentityInvariantError,
    UnknownIdentityError,
)
from etlalchemy.iam.aggregates.user import User


def replay(events: list[Any]) -> User:
    """Rebuilds a user by applying the given events in order."""
    aggregate: Any = None
    for event in events:
        aggregate = event.mutate(aggregate)
    assert isinstance(aggregate, User)
    return aggregate


def test_started_event_carries_the_normalised_identity() -> None:
    """Creating a user records Started and starts active, non-admin."""
    user = User("alice", "alice@example.com", "Alice")

    assert (user.username, user.email, user.display_name) == (
        "alice",
        "alice@example.com",
        "Alice",
    )
    assert user.status == "ACTIVE"
    assert user.is_system_admin is False
    assert user.identities == {}
    assert user.memberships == {}

    event = user.collect_events()[0]
    assert isinstance(event, User.Started)
    assert event.username == "alice"


def test_identities_attach_and_detach_through_replay() -> None:
    """Identity references record their type and provider and survive replay."""
    user = User("alice", "alice@example.com")
    identity_id = uuid4()
    user.attach_identity(identity_id, "PASSWORD", "local")

    restored = replay(user.pending_events)
    assert restored.identities[identity_id].identity_type == "PASSWORD"
    assert restored.identities[identity_id].provider == "local"

    user.detach_identity(identity_id)
    assert user.identities == {}
    assert replay(user.pending_events).identities == {}


def test_attaching_the_same_identity_twice_is_rejected() -> None:
    """An identity can be attached only once."""
    user = User("alice", "alice@example.com")
    identity_id = uuid4()
    user.attach_identity(identity_id, "PASSWORD", "local")

    with pytest.raises(DuplicateIdentityError):
        user.attach_identity(identity_id, "PASSWORD", "local")


def test_detaching_an_unknown_identity_is_rejected() -> None:
    """Detaching an identity the user does not own is an unknown error."""
    with pytest.raises(UnknownIdentityError):
        User("alice", "alice@example.com").detach_identity(uuid4())


def test_system_admin_requires_a_password_identity() -> None:
    """A user without a password identity cannot become a system admin."""
    user = User("alice", "alice@example.com")
    with pytest.raises(IdentityInvariantError):
        user.grant_system_admin("admin")

    user.attach_identity(uuid4(), "PASSWORD", "local")
    user.grant_system_admin("bootstrap")
    assert user.is_system_admin is True
    event = user.collect_events()[-1]
    assert isinstance(event, User.SystemAdminGranted)
    assert event.source == "bootstrap"

    user.revoke_system_admin()
    assert user.is_system_admin is False


def test_tenant_memberships_round_trip() -> None:
    """Joining and leaving a tenant is replayable."""
    user = User("alice", "alice@example.com")
    tenant_id = uuid4()
    user.join_tenant(tenant_id, joined_at=user.created_on)
    assert tenant_id in user.memberships
    assert tenant_id in replay(user.pending_events).memberships

    user.leave_tenant(tenant_id)
    assert user.memberships == {}
    assert replay(user.pending_events).memberships == {}


def test_discarded_user_rejects_every_command() -> None:
    """A discarded user refuses changes and membership updates."""
    user = User("alice", "alice@example.com")
    user.discard()

    with pytest.raises(DiscardedError):
        user.change(display_name="x")
    with pytest.raises(DiscardedError):
        user.join_tenant(uuid4(), joined_at=user.created_on)
    with pytest.raises(DiscardedError):
        user.discard()
