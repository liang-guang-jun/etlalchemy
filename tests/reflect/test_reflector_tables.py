"""Reflector.tables delegates to ReflectionSession.tables."""

from __future__ import annotations

from pathlib import Path
import pytest
from etlalchemy.reflect import reflector as reflector_module
from etlalchemy.reflect.reflector import Reflector
from etlalchemy.reflect.repositories import InMemoryReflectionRepository
from etlalchemy.reflect.source import ReflectSource
from etlalchemy.reflect.table import ReflectedColumn, ReflectedTable

from reflect.helpers import SessionSpy, sqlite_source


def _table(name: str) -> ReflectedTable:
    """Return a one-column reflected table."""
    return ReflectedTable(
        name=name,
        columns=(ReflectedColumn(name="id", sa_type="INTEGER", nullable=False),),
        primary_key=("id",),
    )


def test_reflector_tables_calls_session_tables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reflector must use session.tables(), not one session.table per name."""
    SessionSpy.reset(tables=(_table("a"), _table("b")))
    monkeypatch.setattr(reflector_module, "ReflectionSession", SessionSpy)

    reflector = Reflector(
        ReflectSource(connection_url="sqlite://"),
        InMemoryReflectionRepository(),
    )
    result = reflector.tables(("b", "a"))

    assert SessionSpy.instances[0].calls == [("tables",)]
    assert tuple(table.name for table in result) == ("a", "b")


def test_reflector_tables_sorts_and_deduplicates_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The table selection is sorted and deduplicated before the session."""
    SessionSpy.reset()
    monkeypatch.setattr(reflector_module, "ReflectionSession", SessionSpy)

    reflector = Reflector(
        ReflectSource(connection_url="sqlite://"),
        InMemoryReflectionRepository(),
    )
    reflector.tables(("b", "a", "b"))

    assert SessionSpy.instances[0].table_names == ("a", "b")


def test_tables_of_an_empty_selection_reflects_the_whole_schema(
    tmp_path: Path,
) -> None:
    """``tables(())`` reflects every table of the schema."""
    source = sqlite_source(tmp_path)
    reflector = Reflector(source, InMemoryReflectionRepository())

    assert [table.name for table in reflector.tables(())] == ["orders", "users"]
