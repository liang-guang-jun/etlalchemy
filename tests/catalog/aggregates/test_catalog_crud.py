"""Tests for catalog change, discard and schema rename operations."""

from typing import Any
from uuid import uuid4

import pytest

from etlalchemy.catalog.aggregates.catalog import Catalog
from etlalchemy.catalog.aggregates.errors import (
    DiscardedError,
    DuplicateSchemaError,
    UnknownSchemaError,
)


def replay(events: list[Any]) -> Catalog:
    """Rebuilds a catalog by applying the given events in order."""
    aggregate: Any = None
    for event in events:
        aggregate = event.mutate(aggregate)
    assert isinstance(aggregate, Catalog)
    return aggregate


def test_change_updates_name_and_description() -> None:
    """change() records the new values and updates the aggregate."""
    catalog = Catalog("analytics")
    catalog.collect_events()

    catalog.change(name="warehouse", description="Warehouse catalog")

    assert (catalog.name, catalog.description) == ("warehouse", "Warehouse catalog")
    event = catalog.collect_events()[-1]
    assert isinstance(event, Catalog.Changed)
    assert (event.name, event.description) == ("warehouse", "Warehouse catalog")


def test_change_only_updates_the_given_fields() -> None:
    """A None value leaves the corresponding attribute unchanged."""
    catalog = Catalog("analytics", "Original")

    catalog.change(description="Updated")

    assert (catalog.name, catalog.description) == ("analytics", "Updated")


def test_change_requires_at_least_one_field() -> None:
    """An empty change records nothing."""
    catalog = Catalog("analytics")
    catalog.collect_events()

    with pytest.raises(ValueError, match="name or description"):
        catalog.change()

    assert catalog.collect_events() == []
    assert (catalog.name, catalog.description) == ("analytics", "")


def test_discard_marks_the_catalog_and_blocks_every_change() -> None:
    """A discarded catalog rejects all commands."""
    catalog = Catalog("analytics")
    catalog.discard()

    assert catalog._is_discarded is True
    assert isinstance(catalog.collect_events()[-1], Catalog.Discarded)

    with pytest.raises(DiscardedError, match="catalog is discarded"):
        catalog.change(name="other")
    with pytest.raises(DiscardedError):
        catalog.register_schema("sales", uuid4())
    with pytest.raises(DiscardedError):
        catalog.unregister_schema("sales")
    with pytest.raises(DiscardedError):
        catalog.rename_schema(uuid4(), "other")
    with pytest.raises(DiscardedError):
        catalog.discard()


def test_rename_schema_updates_the_registry() -> None:
    """rename_schema keeps the name to id registry consistent."""
    catalog = Catalog("analytics")
    schema_id = uuid4()
    catalog.register_schema("sales", schema_id)
    catalog.collect_events()

    catalog.rename_schema(schema_id, "revenue")

    assert catalog.schemas == {"revenue": schema_id}
    assert catalog.schema_id("revenue") == schema_id
    event = catalog.collect_events()[-1]
    assert isinstance(event, Catalog.SchemaNameChanged)
    assert (event.schema_id, event.new_name) == (schema_id, "revenue")


def test_rename_schema_rejects_an_unknown_schema() -> None:
    """Renaming an unregistered schema fails."""
    catalog = Catalog("analytics")

    with pytest.raises(UnknownSchemaError):
        catalog.rename_schema(uuid4(), "revenue")


def test_rename_schema_rejects_a_name_in_use() -> None:
    """Two schemas cannot share one name."""
    catalog = Catalog("analytics")
    first, second = uuid4(), uuid4()
    catalog.register_schema("sales", first)
    catalog.register_schema("staging", second)

    with pytest.raises(DuplicateSchemaError, match="staging"):
        catalog.rename_schema(first, "staging")

    assert catalog.schemas == {"sales": first, "staging": second}


def test_schema_name_change_replays_idempotently() -> None:
    """Replaying the rename leaves the registry unchanged."""
    catalog = Catalog("analytics")
    schema_id = uuid4()
    catalog.register_schema("sales", schema_id)
    catalog.rename_schema(schema_id, "revenue")

    replayed = replay(catalog.collect_events())
    replayed.rename_schema(schema_id, "revenue")

    assert replayed.schemas == {"revenue": schema_id}
