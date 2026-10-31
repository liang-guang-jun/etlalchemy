"""Tests for a ReflectionSession: caching, selection and schema handling."""

from __future__ import annotations

from pathlib import Path

import etlalchemy.reflect.inspector as inspector_module
import pytest
from etlalchemy.reflect import (
    InMemoryReflectionRepository,
    JsonReflectionRepository,
    ReflectionSession,
    Reflector,
)
from etlalchemy.semantic.types import String

from reflect.helpers import RecordingInspector, RecordingRepository, sqlite_source


def test_session_saves_what_it_reflected(tmp_path: Path) -> None:
    """A session writes its partial reflection to the shared repository."""
    source = sqlite_source(tmp_path)
    repository = RecordingRepository()
    reflector = Reflector(source, repository)

    with reflector.session() as session:
        assert isinstance(session, ReflectionSession)
        session.table("users")

    key, complete = repository.saved[0]
    assert complete is False
    assert [table.name for table in repository.get(key) or ()] == ["users"]

    completed = reflector.all_tables()
    assert [table.name for table in completed] == ["orders", "users"]


def test_session_rejects_a_table_outside_the_selection(tmp_path: Path) -> None:
    """A session only reflects the tables it selects."""
    source = sqlite_source(tmp_path)
    repository = InMemoryReflectionRepository()

    with Reflector(source, repository).session(table_names=("users",)) as session:
        session.table("users")
        with pytest.raises(ValueError, match="not part of the reflected selection"):
            session.table("orders")


def test_session_table_names_reads_the_schema_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A complete reflection serves the table names from the cache."""
    source = sqlite_source(tmp_path)
    repository = InMemoryReflectionRepository()
    reflector = Reflector(source, repository)
    reflector.all_tables()

    def fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("the cached reflection must not list tables")

    monkeypatch.setattr(inspector_module.LiveInspector, "table_names", fail)
    with reflector.session() as session:
        assert session.table_names == ("orders", "users")


def test_session_tables_completes_a_partial_cache(tmp_path: Path) -> None:
    """A partial cache still lists every table of the schema."""
    source = sqlite_source(tmp_path)
    repository = InMemoryReflectionRepository()
    reflector = Reflector(source, repository)

    with reflector.session(table_names=("users",)) as session:
        session.table("users")

    with reflector.session() as session:
        assert [table.name for table in session.tables()] == ["orders", "users"]


def test_session_joins_catalog_and_schema_for_the_inspector(
    tmp_path: Path,
) -> None:
    """A catalog and a schema are joined into one inspector schema argument."""
    source = sqlite_source(tmp_path)
    fake = RecordingInspector(names=("a", "b"))
    session = ReflectionSession(
        source,
        repository=InMemoryReflectionRepository(),
        catalog="main",
        schema="shop",
        inspector_factory=lambda source: fake,
    )

    assert session.table_names == ("a", "b")

    assert fake.calls == ["names:main.shop"]


def test_session_uses_a_custom_schema_argument(tmp_path: Path) -> None:
    """A custom schema argument overrides the catalog/schema default."""
    source = sqlite_source(tmp_path)
    fake = RecordingInspector(names=("a", "b"))
    session = ReflectionSession(
        source,
        repository=InMemoryReflectionRepository(),
        catalog="cat",
        schema="sch",
        inspector_factory=lambda source: fake,
        schema_argument=lambda catalog, schema: "flat",
    )

    with session:
        assert [table.name for table in session.tables()] == ["a", "b"]

    assert fake.calls == ["names:flat", "table:a:flat", "table:b:flat", "close"]


def test_cache_key_is_per_selection(tmp_path: Path) -> None:
    """Every table selection gets its own cache entry."""
    source = sqlite_source(tmp_path)
    repository = InMemoryReflectionRepository()
    reflector = Reflector(source, repository)

    reflector.table("users")
    reflector.table("orders")

    assert len(repository) == 2


def test_cache_key_is_per_connection(tmp_path: Path) -> None:
    """Two databases never share a cache entry."""
    nested = tmp_path / "nested"
    nested.mkdir()
    first = sqlite_source(nested)
    second = sqlite_source(tmp_path)
    repository = InMemoryReflectionRepository()

    Reflector(first, repository).all_tables()
    Reflector(second, repository).all_tables()

    assert len(repository) == 2


def test_cached_tables_still_build_a_rowset(tmp_path: Path) -> None:
    """A table read back from a file cache maps its stored type strings."""
    source = sqlite_source(tmp_path)
    repository = JsonReflectionRepository(tmp_path / "store")
    Reflector(source, repository).all_tables()

    cached = Reflector(source, repository).all_tables()

    users = cached[1]
    assert users.name == "users"
    assert users.sqlalchemy_table is None
    assert users.as_rowset().fields["name"].data_type == String(20)


def test_session_records_where_a_table_was_reflected(tmp_path: Path) -> None:
    """A reflected table carries the catalog and the schema of its source."""
    source = sqlite_source(tmp_path)
    session = ReflectionSession(
        source,
        repository=InMemoryReflectionRepository(),
        catalog="main",
        schema="shop",
        inspector_factory=lambda source: RecordingInspector(names=("alpha",)),
    )

    table = session.table("alpha")

    assert table.catalog == "main"
    assert table.schema == "shop"
    assert table.as_rowset().sql_name == "main.shop.alpha"


def test_the_cache_keeps_the_source_location(tmp_path: Path) -> None:
    """A table read back from a file cache still names the table it came from."""
    source = sqlite_source(tmp_path)
    repository = JsonReflectionRepository(tmp_path / "store")
    fake = RecordingInspector(names=("alpha",))

    def inspector(source: object) -> RecordingInspector:
        return fake

    with ReflectionSession(
        source,
        repository=repository,
        catalog="main",
        schema="shop",
        inspector_factory=inspector,
    ) as session:
        session.table("alpha")

    with ReflectionSession(
        source,
        repository=repository,
        catalog="main",
        schema="shop",
        inspector_factory=inspector,
    ) as reloaded:
        cached = reloaded.table("alpha")

    assert fake.calls.count("table:alpha:main.shop") == 1
    assert cached.catalog == "main"
    assert cached.schema == "shop"
    assert cached.as_rowset().sql_name == "main.shop.alpha"
