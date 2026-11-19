"""Tests for the domain aggregate."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, is_dataclass
from typing import Any
from uuid import uuid4

import pytest
from etlalchemy.vocabulary.aggregates.domain import Domain
from etlalchemy.vocabulary.aggregates.errors import (
    DiscardedError,
    DuplicateTermError,
    UnknownTermError,
)

EVENT_CLASSES = [
    Domain.Started,
    Domain.TermRegistered,
    Domain.TermUnregistered,
    Domain.TermRepathed,
    Domain.Changed,
    Domain.Discarded,
]


def replay(events: list[Any]) -> Domain:
    """Rebuilds a domain by applying the given events in order."""
    aggregate: Any = None
    for event in events:
        aggregate = event.mutate(aggregate)
    assert isinstance(aggregate, Domain)
    return aggregate


def test_creating_a_domain_records_a_started_event() -> None:
    """Creating a domain stores its attributes and records Domain.Started."""
    domain = Domain("finance", "Finance vocabulary")

    assert domain.name == "finance"
    assert domain.description == "Finance vocabulary"
    assert domain.terms == {}

    events = domain.collect_events()
    assert len(events) == 1
    assert isinstance(events[0], Domain.Started)
    assert events[0].name == "finance"
    assert events[0].description == "Finance vocabulary"
    assert events[0].originator_version == 1


def test_event_classes_are_frozen_dataclasses() -> None:
    """Every domain event is an explicitly declared frozen dataclass."""
    for event_class in EVENT_CLASSES:
        assert is_dataclass(event_class), event_class.__qualname__
        assert event_class.__dataclass_params__.frozen, event_class.__qualname__


def test_events_cannot_be_mutated_after_creation() -> None:
    """Domain events are immutable."""
    event = Domain("finance").collect_events()[0]

    with pytest.raises(FrozenInstanceError):
        event.name = "other"  # type: ignore[misc]


def test_registering_a_term_records_its_path_and_id() -> None:
    """A registered term is reachable by path, and the event records both."""
    domain = Domain("finance")
    term_id = uuid4()
    domain.collect_events()

    domain.register_term("Revenue", term_id)
    domain.register_term("Revenue/ARR", uuid4())

    assert domain.terms["Revenue"] == term_id
    assert domain.term_id("Revenue") == term_id
    assert domain.has_term(term_id)
    event = domain.collect_events()[-1]
    assert isinstance(event, Domain.TermRegistered)
    assert event.term_path == "Revenue/ARR"
    assert event.originator_version == 3


def test_registering_a_duplicate_path_is_rejected() -> None:
    """A path is unique within a domain."""
    domain = Domain("finance")
    domain.register_term("Revenue/ARR", uuid4())
    domain.collect_events()
    version = domain.version

    with pytest.raises(DuplicateTermError, match="Revenue/ARR"):
        domain.register_term("Revenue/ARR", uuid4())

    assert domain.version == version
    assert domain.collect_events() == []


def test_unregistering_a_term_removes_its_path() -> None:
    """Unregistering drops the path to id mapping."""
    domain = Domain("finance")
    term_id = uuid4()
    domain.register_term("Revenue", term_id)
    domain.collect_events()
    domain.unregister_term("Revenue")

    assert domain.terms == {}
    assert not domain.has_term(term_id)
    event = domain.collect_events()[-1]
    assert isinstance(event, Domain.TermUnregistered)
    assert event.term_path == "Revenue"


def test_unregistering_an_unknown_path_is_rejected() -> None:
    """Removing a path that was never registered raises UnknownTermError."""
    domain = Domain("finance")

    with pytest.raises(UnknownTermError, match="Revenue"):
        domain.unregister_term("Revenue")


def test_repath_term_keeps_the_registry_consistent() -> None:
    """The old path disappears and the new one points at the same id."""
    domain = Domain("finance")
    term_id = uuid4()
    domain.register_term("Revenue/ARR", term_id)
    domain.collect_events()

    domain.repath_term(term_id, "Sales/ARR")

    assert domain.terms == {"Sales/ARR": term_id}
    assert domain.has_term(term_id)
    event = domain.collect_events()[-1]
    assert isinstance(event, Domain.TermRepathed)
    assert event.term_id == term_id
    assert event.new_path == "Sales/ARR"


def test_repath_term_rejects_another_terms_path() -> None:
    """A repath may not steal a path registered by a different term."""
    domain = Domain("finance")
    first, second = uuid4(), uuid4()
    domain.register_term("Revenue/ARR", first)
    domain.register_term("Sales/ARR", second)
    domain.collect_events()

    with pytest.raises(DuplicateTermError, match="Sales/ARR"):
        domain.repath_term(first, "Sales/ARR")

    assert domain.collect_events() == []
    assert domain.terms == {"Revenue/ARR": first, "Sales/ARR": second}


def test_repath_term_rejects_an_unregistered_id() -> None:
    """A repath needs a term that the domain knows."""
    domain = Domain("finance")

    with pytest.raises(UnknownTermError):
        domain.repath_term(uuid4(), "Revenue")


def test_change_requires_at_least_one_attribute() -> None:
    """An empty change is rejected without recording an event."""
    domain = Domain("finance")
    domain.collect_events()

    with pytest.raises(ValueError, match="requires a new name"):
        domain.change()


def test_change_updates_only_the_given_attributes() -> None:
    """A name-only change keeps the description and vice versa."""
    domain = Domain("finance", "Finance vocabulary")

    domain.change(name="fp&a")

    assert (domain.name, domain.description) == ("fp&a", "Finance vocabulary")


def test_discarding_a_domain_blocks_every_command() -> None:
    """A discarded domain rejects further mutations with DiscardedError."""
    domain = Domain("finance")
    domain.discard()

    for command in (
        lambda: domain.register_term("Revenue", uuid4()),
        lambda: domain.change(name="other"),
        lambda: domain.discard(),
    ):
        with pytest.raises(DiscardedError, match="discarded"):
            command()


def test_replay_restores_the_registry() -> None:
    """Replaying the collected events rebuilds the same registry."""
    domain = Domain("finance")
    term_id = uuid4()
    domain.register_term("Revenue", term_id)
    domain.register_term("Revenue/ARR", uuid4())
    domain.repath_term(term_id, "Sales")

    replayed = replay(domain.collect_events())

    assert replayed.name == "finance"
    assert replayed.terms["Sales"] == term_id
    assert replayed.has_term(term_id)
    assert "Revenue" not in replayed.terms
