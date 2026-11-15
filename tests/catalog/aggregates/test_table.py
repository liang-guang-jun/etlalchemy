"""Tests for the table aggregate."""

from dataclasses import is_dataclass
from typing import Any
from uuid import uuid4

import pytest

from etlalchemy.catalog.aggregates.errors import (
    DiscardedError,
    DuplicateFieldError,
    UnknownFieldError,
)
from etlalchemy.catalog.aggregates.table import Field, Table
from etlalchemy.catalog.aggregates.types import DataType

EVENT_CLASSES = [
    Table.Started,
    Table.FieldAdded,
    Table.FieldRemoved,
    Table.FieldTypeChanged,
    Table.FieldNullabilityChanged,
    Table.FieldCommentChanged,
]


def replay(events: list[Any]) -> Table:
    """Rebuilds a table by applying the given events in order."""
    aggregate: Any = None
    for event in events:
        aggregate = event.mutate(aggregate)
    assert isinstance(aggregate, Table)
    return aggregate


def test_creating_a_table_records_schema_and_name() -> None:
    """Creating a table stores its schema reference and name."""
    schema_id = uuid4()
    table = Table(schema_id=schema_id, name="orders")

    assert table.schema_id == schema_id
    assert table.name == "orders"
    assert table.fields == {}

    events = table.collect_events()
    assert len(events) == 1
    assert isinstance(events[0], Table.Started)
    assert events[0].schema_id == schema_id
    assert events[0].name == "orders"
    assert events[0].originator_version == 1


def test_event_classes_are_dataclasses() -> None:
    """Every table event is an explicitly declared dataclass."""
    for event_class in EVENT_CLASSES:
        assert is_dataclass(event_class), event_class.__qualname__


def test_adding_a_field_stores_it_and_records_an_event() -> None:
    """Adding a field stores a Field object and records Table.FieldAdded."""
    table = Table(schema_id=uuid4(), name="orders")
    table.collect_events()

    table.add_field("id", DataType.parse("integer"), nullable=False)

    field = table.fields["id"]
    assert isinstance(field, Field)
    assert field.name == "id"
    assert field.data_type == DataType.parse("integer")
    assert field.nullable is False

    event = table.collect_events()[-1]
    assert isinstance(event, Table.FieldAdded)
    assert event.field_name == "id"
    assert event.data_type == DataType.parse("integer")
    assert event.nullable is False
    assert event.originator_version == 2


def test_fields_are_nullable_by_default() -> None:
    """Nullability defaults to True when it is not given."""
    table = Table(schema_id=uuid4(), name="orders")

    table.add_field("note", DataType.parse("text"))

    assert table.fields["note"].nullable is True


def test_adding_a_duplicate_field_is_rejected() -> None:
    """A field name is unique within a table."""
    table = Table(schema_id=uuid4(), name="orders")
    table.add_field("id", DataType.parse("integer"))
    table.collect_events()
    version = table.version

    with pytest.raises(DuplicateFieldError, match="id"):
        table.add_field("id", DataType.parse("text"))

    assert table.version == version
    assert table.collect_events() == []


def test_removing_a_field_drops_it_and_records_an_event() -> None:
    """Removing a field drops it and records Table.FieldRemoved."""
    table = Table(schema_id=uuid4(), name="orders")
    table.add_field("id", DataType.parse("integer"))
    table.collect_events()

    table.remove_field("id")

    assert table.fields == {}
    event = table.collect_events()[-1]
    assert isinstance(event, Table.FieldRemoved)
    assert event.field_name == "id"


def test_removing_an_unknown_field_is_rejected() -> None:
    """Removing a field that does not exist raises UnknownFieldError."""
    table = Table(schema_id=uuid4(), name="orders")

    with pytest.raises(UnknownFieldError, match="id"):
        table.remove_field("id")


def test_changing_a_field_records_the_requested_changes() -> None:
    """Type and nullability changes are recorded by separate events."""
    table = Table(schema_id=uuid4(), name="orders")
    table.add_field("id", DataType.parse("integer"), nullable=False)
    table.collect_events()

    table.change_field("id", data_type=DataType.parse("bigint"))

    field = table.fields["id"]
    assert field.data_type == DataType.parse("bigint")
    assert field.nullable is False

    events = table.collect_events()
    assert len(events) == 1
    event = events[0]
    assert isinstance(event, Table.FieldTypeChanged)
    assert event.field_name == "id"
    assert event.data_type == DataType.parse("bigint")


def test_changing_nullability_does_not_repeat_the_data_type() -> None:
    """A nullability-only change records FieldNullabilityChanged."""
    table = Table(schema_id=uuid4(), name="orders")
    table.add_field("id", DataType.parse("integer"), nullable=True)
    table.collect_events()

    table.change_field("id", nullable=False)

    events = table.collect_events()
    assert len(events) == 1
    event = events[0]
    assert isinstance(event, Table.FieldNullabilityChanged)
    assert event.field_name == "id"
    assert event.nullable is False


def test_changing_both_attributes_records_two_events() -> None:
    """Changing the type and the nullability records one event for each."""
    table = Table(schema_id=uuid4(), name="orders")
    table.add_field("id", DataType.parse("integer"), nullable=True)
    table.collect_events()

    table.change_field("id", data_type=DataType.parse("bigint"), nullable=False)

    events = table.collect_events()
    assert [type(event) for event in events] == [
        Table.FieldTypeChanged,
        Table.FieldNullabilityChanged,
    ]


def test_changing_a_field_requires_a_change() -> None:
    """change_field() rejects calls that request no change at all."""
    table = Table(schema_id=uuid4(), name="orders")
    table.add_field("id", DataType.parse("integer"))
    table.collect_events()
    version = table.version

    with pytest.raises(ValueError, match="data_type or nullable"):
        table.change_field("id")

    assert table.fields["id"].data_type == DataType.parse("integer")
    assert table.version == version
    assert table.collect_events() == []


def test_changing_an_unknown_field_is_rejected() -> None:
    """Changing a field that does not exist raises UnknownFieldError."""
    table = Table(schema_id=uuid4(), name="orders")

    with pytest.raises(UnknownFieldError, match="id"):
        table.change_field("id", nullable=False)


def test_changing_the_field_comment_records_one_event() -> None:
    """A comment change is recorded by FieldCommentChanged."""
    table = Table(schema_id=uuid4(), name="orders")
    table.add_field("amount", DataType.parse("numeric"))
    table.collect_events()

    table.change_field_comment("amount", "Net revenue in EUR.")

    assert table.fields["amount"].comment == "Net revenue in EUR."
    events = table.collect_events()
    assert len(events) == 1
    event = events[0]
    assert isinstance(event, Table.FieldCommentChanged)
    assert event.field_name == "amount"
    assert event.comment == "Net revenue in EUR."


def test_repeating_the_same_comment_records_nothing() -> None:
    """An equal comment is not recorded again."""
    table = Table(schema_id=uuid4(), name="orders")
    table.add_field("amount", DataType.parse("numeric"))
    table.change_field_comment("amount", "Net revenue in EUR.")
    table.collect_events()
    version = table.version

    table.change_field_comment("amount", "Net revenue in EUR.")

    assert table.version == version
    assert table.collect_events() == []


def test_an_empty_comment_clears_the_field_comment() -> None:
    """Clearing a comment is recorded like any other change."""
    table = Table(schema_id=uuid4(), name="orders")
    table.add_field("amount", DataType.parse("numeric"))
    table.change_field_comment("amount", "Net revenue in EUR.")
    table.collect_events()

    table.change_field_comment("amount", "")

    assert table.fields["amount"].comment == ""
    event = table.collect_events()[0]
    assert isinstance(event, Table.FieldCommentChanged)
    assert event.comment == ""


def test_commenting_an_unknown_field_is_rejected() -> None:
    """Commenting a field that does not exist raises UnknownFieldError."""
    table = Table(schema_id=uuid4(), name="orders")

    with pytest.raises(UnknownFieldError, match="amount"):
        table.change_field_comment("amount", "Net revenue in EUR.")


def test_commenting_a_field_of_a_discarded_table_is_rejected() -> None:
    """A discarded table rejects comment changes."""
    table = Table(schema_id=uuid4(), name="orders")
    table.add_field("amount", DataType.parse("numeric"))
    table.discard()

    with pytest.raises(DiscardedError):
        table.change_field_comment("amount", "Net revenue in EUR.")


def test_replaying_events_rebuilds_the_table() -> None:
    """Applying the recorded events reconstructs the table state."""
    schema_id = uuid4()
    table = Table(schema_id=schema_id, name="orders")
    table.add_field("id", DataType.parse("integer"), nullable=False)
    table.add_field("note", DataType.parse("text"))
    table.change_field("note", data_type=DataType.parse("varchar"))
    table.change_field("id", nullable=True)
    table.remove_field("note")

    replayed = replay(table.collect_events())

    assert replayed.id == table.id
    assert replayed.version == table.version
    assert replayed.schema_id == schema_id
    assert replayed.name == "orders"
    assert list(replayed.fields) == ["id"]
    assert replayed.fields["id"].data_type == DataType.parse("integer")
    assert replayed.fields["id"].nullable is True
