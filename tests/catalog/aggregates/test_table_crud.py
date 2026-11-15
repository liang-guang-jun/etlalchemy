"""Tests for table change and discard operations."""

from uuid import uuid4

import pytest

from etlalchemy.catalog.aggregates.errors import DiscardedError
from etlalchemy.catalog.aggregates.table import Table
from etlalchemy.catalog.aggregates.types import DataType


def test_change_updates_the_name() -> None:
    """change() records the new name and updates the aggregate."""
    table = Table(schema_id=uuid4(), name="orders")
    table.collect_events()

    table.change(name="purchases")

    assert table.name == "purchases"
    event = table.collect_events()[-1]
    assert isinstance(event, Table.Changed)
    assert event.name == "purchases"


def test_change_requires_a_name() -> None:
    """An empty change records nothing."""
    table = Table(schema_id=uuid4(), name="orders")
    table.collect_events()

    with pytest.raises(ValueError, match="new name"):
        table.change()

    assert table.collect_events() == []
    assert table.name == "orders"


def test_discard_marks_the_table_and_blocks_every_change() -> None:
    """A discarded table rejects all commands."""
    table = Table(schema_id=uuid4(), name="orders")
    table.add_field("id", DataType.parse("integer"))
    table.discard()

    assert table._is_discarded is True
    assert isinstance(table.collect_events()[-1], Table.Discarded)

    with pytest.raises(DiscardedError, match="table is discarded"):
        table.change(name="purchases")
    with pytest.raises(DiscardedError):
        table.add_field("note", DataType.parse("text"))
    with pytest.raises(DiscardedError):
        table.remove_field("id")
    with pytest.raises(DiscardedError):
        table.change_field("id", data_type=DataType.parse("bigint"))
    with pytest.raises(DiscardedError):
        table.rename_field("id", "order_id")
    with pytest.raises(DiscardedError):
        table.discard()
