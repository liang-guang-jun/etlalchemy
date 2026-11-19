"""Tests for the catalog aggregate."""

from dataclasses import FrozenInstanceError, is_dataclass
from typing import Any
from uuid import uuid4

import pytest
from etlalchemy.catalog.aggregates.catalog import Catalog
from etlalchemy.catalog.aggregates.errors import (
    DuplicateSchemaError,
    UnknownSchemaError,
)

EVENT_CLASSES = [
    Catalog.Started,
    Catalog.SchemaRegistered,
    Catalog.SchemaUnregistered,
]


def replay(events: list[Any]) -> Catalog:
    """Rebuilds a catalog by applying the given events in order."""
    aggregate: Any = None
    for event in events:
        aggregate = event.mutate(aggregate)
    assert isinstance(aggregate, Catalog)
    return aggregate


def test_creating_a_catalog_records_a_started_event() -> None:
    """Creating a catalog stores its attributes and records Catalog.Started."""
    catalog = Catalog("analytics", "Analytics warehouse")

    assert catalog.name == "analytics"
    assert catalog.description == "Analytics warehouse"
    assert catalog.schemas == {}

    events = catalog.collect_events()
    assert len(events) == 1
    assert isinstance(events[0], Catalog.Started)
    assert events[0].name == "analytics"
    assert events[0].description == "Analytics warehouse"
    assert events[0].originator_id == catalog.id
    assert events[0].originator_version == 1


def test_event_classes_are_frozen_dataclasses() -> None:
    """Every catalog event is an explicitly declared frozen dataclass."""
    for event_class in EVENT_CLASSES:
        assert is_dataclass(event_class), event_class.__qualname__
        assert event_class.__dataclass_params__.frozen, event_class.__qualname__


def test_events_cannot_be_mutated_after_creation() -> None:
    """Catalog events are immutable."""
    event = Catalog("analytics").collect_events()[0]

    with pytest.raises(FrozenInstanceError):
        event.name = "other"  # type: ignore[misc]


def test_registering_a_schema_records_its_id() -> None:
    """A registered schema is reachable by name, and the event records both."""
    catalog = Catalog("analytics")
    schema_id = uuid4()
    catalog.collect_events()

    catalog.register_schema("sales", schema_id)

    assert catalog.schemas == {"sales": schema_id}
    assert catalog.schema_id("sales") == schema_id
    event = catalog.collect_events()[-1]
    assert isinstance(event, Catalog.SchemaRegistered)
    assert event.schema_name == "sales"
    assert event.schema_id == schema_id
    assert event.originator_version == 2


def test_registering_a_duplicate_schema_is_rejected() -> None:
    """A schema name is unique within a catalog."""
    catalog = Catalog("analytics")
    catalog.register_schema("sales", uuid4())
    catalog.collect_events()
    version = catalog.version

    with pytest.raises(DuplicateSchemaError, match="sales"):
        catalog.register_schema("sales", uuid4())

    assert catalog.version == version
    assert catalog.collect_events() == []


def test_unregistering_a_schema_removes_it() -> None:
    """Unregistering drops the name to id mapping."""
    catalog = Catalog("analytics")
    catalog.register_schema("sales", uuid4())
    catalog.collect_events()

    catalog.unregister_schema("sales")

    assert catalog.schemas == {}
    event = catalog.collect_events()[-1]
    assert isinstance(event, Catalog.SchemaUnregistered)
    assert event.schema_name == "sales"


def test_unregistering_an_unknown_schema_is_rejected() -> None:
    """Removing a schema that was never registered raises UnknownSchemaError."""
    catalog = Catalog("analytics")

    with pytest.raises(UnknownSchemaError, match="warehouse"):
        catalog.unregister_schema("warehouse")


def test_looking_up_an_unknown_schema_is_rejected() -> None:
    """Looking up a schema that was never registered raises UnknownSchemaError."""
    catalog = Catalog("analytics")

    with pytest.raises(UnknownSchemaError, match="warehouse"):
        catalog.schema_id("warehouse")


def test_replaying_events_rebuilds_the_catalog() -> None:
    """Applying the recorded events reconstructs the catalog state."""
    catalog = Catalog("analytics", "Analytics warehouse")
    sales_id = uuid4()
    staging_id = uuid4()
    catalog.register_schema("sales", sales_id)
    catalog.register_schema("staging", staging_id)
    catalog.unregister_schema("staging")

    events = catalog.collect_events()
    replayed = replay(events)

    assert replayed.id == catalog.id
    assert replayed.version == catalog.version
    assert replayed.name == catalog.name
    assert replayed.description == catalog.description
    assert replayed.schemas == {"sales": sales_id}
