"""Tests for the reflection cache implementations."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import sqlalchemy as sa
from etlalchemy.reflect import (
    InMemoryReflectionRepository,
    JsonReflectionRepository,
    ReflectedColumn,
    ReflectedTable,
    SqlAlchemyReflectionRepository,
    YamlReflectionRepository,
)
from etlalchemy.reflect.serialization import PAYLOAD_VERSION, table_to_dict

from reflect.helpers import reflected_tables, sqlite_source


def _tables(tmp_path: Path) -> tuple[ReflectedTable, ...]:
    """Reflect the sample schema once."""
    return reflected_tables(sqlite_source(tmp_path))


def _normalised(tables: tuple[ReflectedTable, ...]) -> list[dict[str, object]]:
    """Return tables in their serialised form for comparison."""
    return [table_to_dict(table) for table in tables]


def test_in_memory_repository_round_trip(tmp_path: Path) -> None:
    """The in-memory repository stores, returns and clears entries."""
    tables = _tables(tmp_path)
    repository = InMemoryReflectionRepository()

    assert repository.get("key") is None
    repository.save("key", tables, complete=False)
    assert len(repository) == 1
    assert repository.get("key") is not None
    assert repository.get_entry("key") == (tables, False)

    repository.clear("key")
    assert repository.get("key") is None
    assert len(repository) == 0


def test_json_repository_round_trip(tmp_path: Path) -> None:
    """The JSON repository round-trips the payload and its complete flag."""
    tables = _tables(tmp_path)
    repository = JsonReflectionRepository(tmp_path / "cache")

    repository.save("key", tables, complete=True)

    entry = repository.get_entry("key")
    assert entry is not None
    cached, complete = entry
    assert _normalised(cached) == _normalised(tables)
    assert complete is True
    assert (tmp_path / "cache" / "key.json").is_file()

    repository.clear("key")
    assert repository.get("key") is None


def test_json_repository_ignores_a_corrupted_file(tmp_path: Path) -> None:
    """A broken JSON file reads as a cache miss."""
    repository = JsonReflectionRepository(tmp_path)
    (tmp_path / "broken.json").write_text("{not json")

    assert repository.get("broken") is None
    assert repository.get_entry("broken") is None


def test_json_repository_ignores_another_payload_version(tmp_path: Path) -> None:
    """A payload of an unknown version reads as a cache miss."""
    repository = JsonReflectionRepository(tmp_path)
    (tmp_path / "old.json").write_text('{"version": 1, "tables": []}')

    assert repository.get("old") is None


def test_yaml_repository_round_trip(tmp_path: Path) -> None:
    """The YAML repository round-trips the same payload as JSON."""
    pytest.importorskip("yaml")
    tables = _tables(tmp_path)
    repository = YamlReflectionRepository(tmp_path / "cache")

    repository.save("key", tables, complete=False)

    entry = repository.get_entry("key")
    assert entry is not None
    cached, complete = entry
    assert _normalised(cached) == _normalised(tables)
    assert complete is False


def test_sqlalchemy_repository_round_trip(tmp_path: Path) -> None:
    """The SQLAlchemy repository stores rows in an existing engine."""
    tables = _tables(tmp_path)
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'cache.db'}")
    repository = SqlAlchemyReflectionRepository(engine)

    assert repository.get("key") is None
    repository.save("key", tables, complete=True)
    entry = repository.get_entry("key")
    assert entry is not None
    cached, complete = entry
    assert _normalised(cached) == _normalised(tables)
    assert complete is True

    repository.save("key", tables[:1], complete=False)
    partial = repository.get_entry("key")
    assert partial is not None
    assert partial[1] is False

    repository.clear("key")
    assert repository.get("key") is None


def test_raw_tables_keep_the_cached_type_strings(tmp_path: Path) -> None:
    """A deserialised column keeps its type as a string."""
    tables = _tables(tmp_path)
    repository = JsonReflectionRepository(tmp_path)

    repository.save("key", tables, complete=True)

    cached = repository.get("key")
    assert cached is not None
    column = cached[0].columns[0]
    assert isinstance(column, ReflectedColumn)
    assert isinstance(column.sa_type, str)


def test_json_repository_reads_an_empty_payload(tmp_path: Path) -> None:
    """A payload without tables is a valid, complete, empty entry."""
    repository = JsonReflectionRepository(tmp_path)
    (tmp_path / "empty.json").write_text(
        json.dumps({"version": PAYLOAD_VERSION, "complete": True, "tables": []}),
        encoding="utf-8",
    )

    assert repository.get_entry("empty") == ((), True)
    assert repository.get("empty") == ()
