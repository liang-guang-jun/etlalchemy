"""Tests for the tenant aggregate."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from etlalchemy.iam.aggregates.errors import (
    DiscardedError,
    DuplicateMembershipError,
    IamValidationError,
    UnknownMembershipError,
)
from etlalchemy.iam.aggregates.tenant import Tenant

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def replay(events: list[Any]) -> Tenant:
    """Rebuilds a tenant by applying the given events in order."""
    aggregate: Any = None
    for event in events:
        aggregate = event.mutate(aggregate)
    assert isinstance(aggregate, Tenant)
    return aggregate


def test_started_event_carries_the_name() -> None:
    """Creating a tenant records Started and starts active without members."""
    tenant = Tenant("acme", "Acme Corp")

    assert (tenant.name, tenant.description, tenant.status) == ("acme", "Acme Corp", "ACTIVE")
    assert tenant.members == {}

    event = tenant.collect_events()[0]
    assert isinstance(event, Tenant.Started)
    assert event.name == "acme"


def test_blank_name_is_rejected() -> None:
    """A blank tenant name is a validation error."""
    with pytest.raises(IamValidationError):
        Tenant("   ")


def test_change_requires_a_field() -> None:
    """An all-None change is a caller error."""
    with pytest.raises(ValueError):
        Tenant("acme").change()


def test_change_rejects_unknown_status() -> None:
    """Only ACTIVE and SUSPENDED are tenant statuses."""
    with pytest.raises(IamValidationError):
        Tenant("acme").change(status="DELETED")


def test_members_round_trip_through_replay() -> None:
    """Adding and removing members survives a replay of the event stream."""
    tenant = Tenant("acme")
    user_id = uuid4()
    tenant.add_member(user_id, joined_at=NOW)
    assert tenant.has_member(user_id)

    restored = replay(tenant.pending_events)
    assert restored.has_member(user_id)

    tenant.remove_member(user_id)
    restored = replay(tenant.pending_events)
    assert not restored.has_member(user_id)


def test_duplicate_member_is_rejected_without_mutating() -> None:
    """A rejected add leaves the version and the pending events untouched."""
    tenant = Tenant("acme")
    tenant.collect_events()
    user_id = uuid4()
    tenant.add_member(user_id, joined_at=tenant.created_on)
    version = tenant.version
    tenant.collect_events()

    with pytest.raises(DuplicateMembershipError):
        tenant.add_member(user_id, joined_at=tenant.created_on)

    assert tenant.version == version
    assert tenant.collect_events() == []


def test_removing_an_unknown_member_is_rejected() -> None:
    """Removing a member that never joined is an unknown-membership error."""
    with pytest.raises(UnknownMembershipError):
        Tenant("acme").remove_member(uuid4())


def test_discarded_tenant_rejects_every_command() -> None:
    """A discarded tenant refuses changes and membership updates."""
    tenant = Tenant("acme")
    tenant.discard()

    with pytest.raises(DiscardedError):
        tenant.change(description="x")
    with pytest.raises(DiscardedError):
        tenant.add_member(uuid4(), joined_at=tenant.created_on)
    with pytest.raises(DiscardedError):
        tenant.discard()
