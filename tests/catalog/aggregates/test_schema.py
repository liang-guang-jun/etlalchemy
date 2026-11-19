"""Tests for the schema aggregate."""

from dataclasses import is_dataclass
from typing import Any
from uuid import uuid4

import pytest
from etlalchemy.catalog.aggregates.errors import (
    DuplicateTableError,
    UnknownTableError,
)
from etlalchemy.catalog.aggregates.schema import Schema

EVENT_CLASSES = [
    Schema.Started,
    Schema.TableRegistered,
    Schema.TableUnregistered,
]


def replay(events: list[Any]) -> Schema:
    """Rebuilds a schema by applying the given events in order."""
    aggregate: Any = None
    for event in events:
        aggregate = event.mutate(aggregate)
    assert isinstance(aggregate, Schema)
    return aggregate


def test_creating_a_schema_records_catalog_and_name() -> None:
    """Creating a schema stores its catalog reference, name and description."""
    catalog_id = uuid4()
    schema = Schema(catalog_id=catalog_id, name="sales", description="Sales data")

    assert schema.catalog_id == catalog_id
    assert schema.name == "sales"
    assert schema.description == "Sales data"
    assert schema.tables == {}

    events = schema.collect_events()
    assert len(events) == 1
    assert isinstance(events[0], Schema.Started)
    assert events[0].catalog_id == catalog_id
    assert events[0].name == "sales"
    assert events[0].originator_version == 1


def test_event_classes_are_dataclasses() -> None:
    """Every schema event is an explicitly declared dataclass."""
    for event_class in EVENT_CLASSES:
        assert is_dataclass(event_class), event_class.__qualname__


def test_registering_a_table_records_its_id() -> None:
    """A registered table is reachable by name, and the event records both."""
    schema = Schema(catalog_id=uuid4(), name="sales")
    table_id = uuid4()
    schema.collect_events()

    schema.register_table("orders", table_id)

    assert schema.tables == {"orders": table_id}
    assert schema.table_id("orders") == table_id
    event = schema.collect_events()[-1]
    assert isinstance(event, Schema.TableRegistered)
    assert event.table_name == "orders"
    assert event.table_id == table_id
    assert event.originator_version == 2


def test_registering_a_duplicate_table_is_rejected() -> None:
    """A table name is unique within a schema."""
    schema = Schema(catalog_id=uuid4(), name="sales")
    schema.register_table("orders", uuid4())
    schema.collect_events()
    version = schema.version

    with pytest.raises(DuplicateTableError, match="orders"):
        schema.register_table("orders", uuid4())

    assert schema.version == version
    assert schema.collect_events() == []


def test_unregistering_a_table_removes_it() -> None:
    """Unregistering drops the name to id mapping."""
    schema = Schema(catalog_id=uuid4(), name="sales")
    schema.register_table("orders", uuid4())
    schema.collect_events()

    schema.unregister_table("orders")

    assert schema.tables == {}
    event = schema.collect_events()[-1]
    assert isinstance(event, Schema.TableUnregistered)
    assert event.table_name == "orders"


def test_unregistering_an_unknown_table_is_rejected() -> None:
    """Removing a table that was never registered raises UnknownTableError."""
    schema = Schema(catalog_id=uuid4(), name="sales")

    with pytest.raises(UnknownTableError, match="orders"):
        schema.unregister_table("orders")


def test_looking_up_an_unknown_table_is_rejected() -> None:
    """Looking up a table that was never registered raises UnknownTableError."""
    schema = Schema(catalog_id=uuid4(), name="sales")

    with pytest.raises(UnknownTableError, match="orders"):
        schema.table_id("orders")


def test_replaying_events_rebuilds_the_schema() -> None:
    """Applying the recorded events reconstructs the schema state."""
    catalog_id = uuid4()
    schema = Schema(catalog_id=catalog_id, name="sales", description="Sales data")
    orders_id = uuid4()
    staging_id = uuid4()
    schema.register_table("orders", orders_id)
    schema.register_table("staging", staging_id)
    schema.unregister_table("staging")

    replayed = replay(schema.collect_events())

    assert replayed.id == schema.id
    assert replayed.version == schema.version
    assert replayed.catalog_id == catalog_id
    assert replayed.name == "sales"
    assert replayed.description == "Sales data"
    assert replayed.tables == {"orders": orders_id}
