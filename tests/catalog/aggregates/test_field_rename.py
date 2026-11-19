"""Tests for renaming fields of a table."""

from typing import Any
from uuid import uuid4

import pytest
from etlalchemy.catalog.aggregates.errors import DuplicateFieldError, UnknownFieldError
from etlalchemy.catalog.aggregates.table import Table
from etlalchemy.catalog.aggregates.types import DataType


def replay(events: list[Any]) -> Table:
    """Rebuilds a table by applying the given events in order."""
    aggregate: Any = None
    for event in events:
        aggregate = event.mutate(aggregate)
    assert isinstance(aggregate, Table)
    return aggregate


def test_rename_field_replaces_the_key_and_keeps_the_field_state() -> None:
    """The renamed field keeps its type and nullability."""
    table = Table(schema_id=uuid4(), name="orders")
    table.add_field("id", DataType.parse("bigint"), nullable=False)
    table.collect_events()

    table.rename_field("id", "order_id")

    assert list(table.fields) == ["order_id"]
    field = table.fields["order_id"]
    assert (field.name, field.data_type, field.nullable) == (
        "order_id",
        DataType.parse("bigint"),
        False,
    )

    event = table.collect_events()[-1]
    assert isinstance(event, Table.FieldRenamed)
    assert (event.old_name, event.new_name) == ("id", "order_id")


def test_rename_field_rejects_an_unknown_field() -> None:
    """Renaming a field that does not exist fails."""
    table = Table(schema_id=uuid4(), name="orders")

    with pytest.raises(UnknownFieldError, match="id"):
        table.rename_field("id", "order_id")


def test_rename_field_rejects_a_name_in_use() -> None:
    """Two fields cannot share one name."""
    table = Table(schema_id=uuid4(), name="orders")
    table.add_field("id", DataType.parse("bigint"))
    table.add_field("note", DataType.parse("text"))

    with pytest.raises(DuplicateFieldError, match="note"):
        table.rename_field("id", "note")

    assert list(table.fields) == ["id", "note"]


def test_rename_field_replays_idempotently() -> None:
    """Replaying the rename leaving the fields unchanged."""
    table = Table(schema_id=uuid4(), name="orders")
    table.add_field("id", DataType.parse("bigint"), nullable=False)
    table.rename_field("id", "order_id")

    replayed = replay(table.collect_events())
    replayed.rename_field("order_id", "order_id")

    assert list(replayed.fields) == ["order_id"]
    assert replayed.fields["order_id"].data_type == DataType.parse("bigint")
    assert replayed.fields["order_id"].nullable is False
