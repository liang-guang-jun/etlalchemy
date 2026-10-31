"""Tests for the reflect_tables one-shot helper."""

from __future__ import annotations

from pathlib import Path

import pytest
from etlalchemy.reflect import (
    InMemoryReflectionRepository,
    Reflector,
    ReflectSource,
    reflect_tables,
)

from reflect.helpers import sqlite_source


def test_reflect_tables_is_a_one_shot_reflector(tmp_path: Path) -> None:
    """The convenience function reflects the source with the given cache."""
    source = sqlite_source(tmp_path)
    repository = InMemoryReflectionRepository()

    tables = reflect_tables(source, repository=repository)

    assert [table.name for table in tables] == ["orders", "users"]
    assert len(repository) == 1


def test_reflect_tables_accepts_a_ready_made_reflector(tmp_path: Path) -> None:
    """A reflector can be passed in to share one repository."""
    source = sqlite_source(tmp_path)
    repository = InMemoryReflectionRepository()
    reflector = Reflector(source, repository)

    tables = reflect_tables(source, table_names=("users",), reflector=reflector)

    assert [table.name for table in tables] == ["users"]
    assert len(repository) == 1


def test_reflect_tables_requires_repository_when_no_reflector() -> None:
    """The one-shot helper needs a repository when it builds the reflector."""
    with pytest.raises(ValueError, match="repository"):
        reflect_tables(ReflectSource(connection_url="sqlite://"))


def test_reflect_tables_accepts_explicit_repository(tmp_path: Path) -> None:
    """An explicit repository is enough to run the one-shot helper."""
    repository = InMemoryReflectionRepository()
    source = ReflectSource(connection_url=f"sqlite:///{tmp_path / 'empty.db'}")

    tables = reflect_tables(source, repository=repository)

    assert tables == ()
