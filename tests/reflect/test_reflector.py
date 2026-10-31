"""Tests for the Reflector: construction, caches and table selection."""

from __future__ import annotations

import builtins
from pathlib import Path
from types import SimpleNamespace

import etlalchemy.reflect.inspector as inspector_module
import pytest
from etlalchemy.reflect.databricks import databricks_connection
from etlalchemy.reflect import (
    InMemoryReflectionRepository,
    JsonReflectionRepository,
    Reflector,
    ReflectSource,
)

from reflect.helpers import RecordingRepository, add_table, sqlite_source


def test_reflector_reads_back_from_a_json_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A JSON cache written by one call serves the next one."""
    source = sqlite_source(tmp_path)
    directory = tmp_path / "store"
    reflector = Reflector(source, JsonReflectionRepository(directory))

    first = reflector.all_tables()

    assert list(directory.glob("*.json"))

    def fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("the cached reflection must not open a database")

    monkeypatch.setattr(inspector_module.LiveInspector, "__init__", fail)
    second = reflector.all_tables()

    assert [table.name for table in second] == [table.name for table in first]


def test_reflector_builds_without_connecting(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Building a reflector keeps the source and never opens the database."""
    source = sqlite_source(tmp_path)
    repository = InMemoryReflectionRepository()

    def fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("building a reflector must not connect")

    monkeypatch.setattr(inspector_module.LiveInspector, "__init__", fail)

    reflector = Reflector(source, repository)

    assert reflector.source is source
    assert reflector.repository is repository


def test_reflector_reuses_an_explicit_repository(tmp_path: Path) -> None:
    """An explicit repository caches between runs and is cleared on force."""
    source = sqlite_source(tmp_path)
    repository = RecordingRepository()
    reflector = Reflector(source, repository)

    first = reflector.all_tables()
    second = reflector.all_tables()

    assert len(repository) == 1
    assert len(repository.saved) == 1
    assert [table.name for table in second] == [table.name for table in first]

    add_table(source, "payments")
    forced = reflector.all_tables(force=True)

    assert [table.name for table in forced] == ["orders", "payments", "users"]
    assert len(repository) == 1
    assert len(repository.cleared) == 1


def test_reflector_reflects_named_tables(tmp_path: Path) -> None:
    """``table`` and ``tables`` reflect only what they are asked for."""
    source = sqlite_source(tmp_path)
    repository = InMemoryReflectionRepository()
    reflector = Reflector(source, repository)

    users = reflector.table("users")
    pair = reflector.tables(("users", "orders"))

    assert users.name == "users"
    assert users.columns[0].name == "id"
    assert [table.name for table in pair] == ["orders", "users"]
    assert reflector.repository is repository


def test_reflector_defaults_to_an_in_memory_repository() -> None:
    """A reflector without a repository keeps its cache in memory."""
    reflector = Reflector(ReflectSource(connection_url="sqlite://"))

    assert isinstance(reflector.repository, InMemoryReflectionRepository)


def test_reflector_defaults_to_an_auto_detected_source() -> None:
    """``Reflector()`` reflects whatever the runtime already knows about."""
    reflector = Reflector()

    assert reflector.source == ReflectSource()
    assert reflector.source.auto_detect is True
    assert isinstance(reflector.repository, InMemoryReflectionRepository)


def test_a_bare_reflector_finds_the_notebook_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In a Databricks notebook ``Reflector()`` needs no arguments at all."""
    monkeypatch.setattr(
        builtins,
        "dbutils",
        SimpleNamespace(
            notebook=SimpleNamespace(
                entry_point=SimpleNamespace(
                    getDbutils=lambda: SimpleNamespace(
                        notebook=lambda: SimpleNamespace(
                            getContext=lambda: SimpleNamespace(
                                browserHostName=lambda: SimpleNamespace(
                                    get=lambda: "adb-123.azuredatabricks.net"
                                ),
                                apiToken=lambda: SimpleNamespace(
                                    get=lambda: "dapi-from-notebook"
                                ),
                            )
                        )
                    )
                )
            )
        ),
        raising=False,
    )

    url, _ = databricks_connection(Reflector().source)

    assert url.startswith("databricks://token:dapi-from-notebook@adb-123")


def test_reflector_uses_given_repository() -> None:
    """The caller decides where the cache is written."""
    repository = InMemoryReflectionRepository()

    reflector = Reflector(
        ReflectSource(connection_url="sqlite://"),
        repository=repository,
    )

    assert reflector.repository is repository
