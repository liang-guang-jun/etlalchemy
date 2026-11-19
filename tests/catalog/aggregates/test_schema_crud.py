"""Tests for schema change, discard and table rename operations."""

from typing import Any
from uuid import uuid4

import pytest
from etlalchemy.catalog.aggregates.errors import (
    DiscardedError,
    DuplicateTableError,
    UnknownTableError,
)
from etlalchemy.catalog.aggregates.schema import Schema


def replay(events: list[Any]) -> Schema:
    """Rebuilds a schema by applying the given events in order."""
    aggregate: Any = None
    for event in events:
        aggregate = event.mutate(aggregate)
    assert isinstance(aggregate, Schema)
    return aggregate


def test_change_updates_name_and_description() -> None:
    """change() records the new values and updates the aggregate."""
    schema = Schema(catalog_id=uuid4(), name="sales")
    schema.collect_events()

    schema.change(name="revenue", description="Revenue data")

    assert (schema.name, schema.description) == ("revenue", "Revenue data")
    event = schema.collect_events()[-1]
    assert isinstance(event, Schema.Changed)
    assert (event.name, event.description) == ("revenue", "Revenue data")


def test_change_requires_at_least_one_field() -> None:
    """An empty change records nothing."""
    schema = Schema(catalog_id=uuid4(), name="sales")
    schema.collect_events()

    with pytest.raises(ValueError, match="name or description"):
        schema.change()

    assert schema.collect_events() == []


def test_discard_marks_the_schema_and_blocks_every_change() -> None:
    """A discarded schema rejects all commands."""
    schema = Schema(catalog_id=uuid4(), name="sales")
    schema.discard()

    assert schema._is_discarded is True
    assert isinstance(schema.collect_events()[-1], Schema.Discarded)

    with pytest.raises(DiscardedError, match="schema is discarded"):
        schema.change(name="revenue")
    with pytest.raises(DiscardedError):
        schema.register_table("orders", uuid4())
    with pytest.raises(DiscardedError):
        schema.unregister_table("orders")
    with pytest.raises(DiscardedError):
        schema.rename_table(uuid4(), "other")
    with pytest.raises(DiscardedError):
        schema.discard()


def test_rename_table_updates_the_registry() -> None:
    """rename_table keeps the name to id registry consistent."""
    schema = Schema(catalog_id=uuid4(), name="sales")
    table_id = uuid4()
    schema.register_table("orders", table_id)
    schema.collect_events()

    schema.rename_table(table_id, "purchases")

    assert schema.tables == {"purchases": table_id}
    assert schema.table_id("purchases") == table_id
    event = schema.collect_events()[-1]
    assert isinstance(event, Schema.TableNameChanged)
    assert (event.table_id, event.new_name) == (table_id, "purchases")


def test_rename_table_rejects_an_unknown_table() -> None:
    """Renaming an unregistered table fails."""
    schema = Schema(catalog_id=uuid4(), name="sales")

    with pytest.raises(UnknownTableError):
        schema.rename_table(uuid4(), "purchases")


def test_rename_table_rejects_a_name_in_use() -> None:
    """Two tables cannot share one name."""
    schema = Schema(catalog_id=uuid4(), name="sales")
    first, second = uuid4(), uuid4()
    schema.register_table("orders", first)
    schema.register_table("staging", second)

    with pytest.raises(DuplicateTableError, match="staging"):
        schema.rename_table(first, "staging")

    assert schema.tables == {"orders": first, "staging": second}


def test_table_name_change_replays_idempotently() -> None:
    """Replaying the rename leaves the registry unchanged."""
    schema = Schema(catalog_id=uuid4(), name="sales")
    table_id = uuid4()
    schema.register_table("orders", table_id)
    schema.rename_table(table_id, "purchases")

    replayed = replay(schema.collect_events())
    replayed.rename_table(table_id, "purchases")

    assert replayed.tables == {"purchases": table_id}
