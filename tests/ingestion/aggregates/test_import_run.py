"""Tests for the ImportRun aggregate."""

from dataclasses import is_dataclass
from typing import Any
from uuid import uuid4

import pytest

from etlalchemy.ingestion.aggregates.errors import InvalidImportRunStateError
from etlalchemy.ingestion.aggregates.import_run import ImportRun

EVENT_CLASSES = [
    ImportRun.Started,
    ImportRun.Succeeded,
    ImportRun.Failed,
    ImportRun.Abandoned,
]


def replay(events: list[Any]) -> ImportRun:
    """Rebuilds an import run by applying the given events in order."""
    aggregate: Any = None
    for event in events:
        aggregate = event.mutate(aggregate)
    assert isinstance(aggregate, ImportRun)
    return aggregate


def test_creating_a_run_records_a_started_event() -> None:
    """A new run is pending and remembers its three references."""
    connection_id = uuid4()
    catalog_id = uuid4()

    run = ImportRun(
        connection_id=connection_id,
        target_catalog_id=catalog_id,
        source_catalog="src",
        include_schemas=["sales"],
        include_tables={"sales": ["orders"]},
        schema_mapping={"sales": "sales_raw"},
    )

    assert run.connection_id == connection_id
    assert run.target_catalog_id == catalog_id
    assert run.source_catalog == "src"
    assert run.include_schemas == ["sales"]
    assert run.include_tables == {"sales": ["orders"]}
    assert run.schema_mapping == {"sales": "sales_raw"}
    assert run.status == "pending"
    assert (run.schema_count, run.table_count, run.field_count) == (0, 0, 0)
    assert run.error is None

    events = run.collect_events()
    assert len(events) == 1
    assert isinstance(events[0], ImportRun.Started)
    assert events[0].connection_id == connection_id
    assert events[0].target_catalog_id == catalog_id
    assert events[0].source_catalog == "src"
    assert events[0].include_schemas == ["sales"]
    assert events[0].include_tables == {"sales": ["orders"]}
    assert events[0].schema_mapping == {"sales": "sales_raw"}
    assert events[0].originator_version == 1


def test_event_classes_are_dataclasses() -> None:
    """Every import run event is an explicitly declared dataclass."""
    for event_class in EVENT_CLASSES:
        assert is_dataclass(event_class), event_class.__qualname__


def test_include_schemas_is_copied() -> None:
    """Mutating the caller's list does not change the run."""
    schemas = ["sales"]
    run = ImportRun(connection_id=uuid4(), target_catalog_id=uuid4(), include_schemas=schemas)

    schemas.append("marketing")

    assert run.include_schemas == ["sales"]


def test_counters_are_accumulated_in_memory() -> None:
    """The record methods only change the in-memory counters."""
    run = ImportRun(connection_id=uuid4(), target_catalog_id=uuid4())
    run.collect_events()

    run.record_schema()
    run.record_table()
    run.record_field()
    run.record_field()

    assert (run.schema_count, run.table_count, run.field_count) == (1, 1, 2)
    assert run.collect_events() == []


def test_succeed_finalises_the_run() -> None:
    """Succeeding records the final counters and the terminal status."""
    run = ImportRun(connection_id=uuid4(), target_catalog_id=uuid4())
    run.collect_events()

    run.succeed(1, 2, 3)

    assert run.status == "succeeded"
    assert (run.schema_count, run.table_count, run.field_count) == (1, 2, 3)
    event = run.collect_events()[-1]
    assert isinstance(event, ImportRun.Succeeded)
    assert (event.schema_count, event.table_count, event.field_count) == (1, 2, 3)
    assert event.originator_version == 2


def test_fail_finalises_the_run() -> None:
    """Failing records the error, the counters and the terminal status."""
    run = ImportRun(connection_id=uuid4(), target_catalog_id=uuid4())
    run.collect_events()

    run.fail("boom", 1, 0, 0)

    assert run.status == "failed"
    assert run.error == "boom"
    assert (run.schema_count, run.table_count, run.field_count) == (1, 0, 0)
    event = run.collect_events()[-1]
    assert isinstance(event, ImportRun.Failed)
    assert event.error == "boom"


def test_abandon_finalises_a_pending_run() -> None:
    """Abandoning records the reason and the terminal status."""
    run = ImportRun(connection_id=uuid4(), target_catalog_id=uuid4())
    run.collect_events()

    run.abandon("process crashed")

    assert run.status == "abandoned"
    assert run.error == "process crashed"
    event = run.collect_events()[-1]
    assert isinstance(event, ImportRun.Abandoned)
    assert event.reason == "process crashed"
    assert event.originator_version == 2


def test_a_finalised_run_rejects_further_transitions() -> None:
    """A run can only be finalised once."""
    run = ImportRun(connection_id=uuid4(), target_catalog_id=uuid4())
    run.succeed(0, 0, 0)
    run.collect_events()
    version = run.version

    with pytest.raises(InvalidImportRunStateError, match="succeeded"):
        run.succeed(1, 1, 1)
    with pytest.raises(InvalidImportRunStateError, match="succeeded"):
        run.fail("boom", 1, 1, 1)
    with pytest.raises(InvalidImportRunStateError, match="succeeded"):
        run.abandon("crashed")

    assert run.version == version
    assert run.collect_events() == []


def test_replay_restores_the_terminal_state() -> None:
    """Applying Started and Succeeded rebuilds the final counters."""
    run = ImportRun(
        connection_id=uuid4(),
        target_catalog_id=uuid4(),
        source_catalog="src",
        include_schemas=["sales"],
    )
    run.succeed(1, 2, 3)

    restored = replay(list(run.collect_events()))

    assert restored.id == run.id
    assert restored.status == "succeeded"
    assert (restored.schema_count, restored.table_count, restored.field_count) == (1, 2, 3)
    assert restored.version == 2


def test_replay_restores_an_abandoned_state() -> None:
    """Applying Started and Abandoned rebuilds the abandoned run."""
    run = ImportRun(connection_id=uuid4(), target_catalog_id=uuid4())
    run.abandon("crashed")

    restored = replay(list(run.collect_events()))

    assert restored.status == "abandoned"
    assert restored.error == "crashed"
    assert restored.version == 2
