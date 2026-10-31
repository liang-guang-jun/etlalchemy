"""The inspector factory must win over connection resolution."""

from __future__ import annotations

import pytest
from etlalchemy.reflect.inspector import ReflectionSession
from etlalchemy.reflect.repositories import InMemoryReflectionRepository
from etlalchemy.reflect.source import ReflectSource
from reflect.helpers import RecordingInspector


def test_inspector_factory_wins_without_resolving_connection_url() -> None:
    """A source with no connection info must work when a factory is given."""
    source = ReflectSource()  # no connection_url, no profile, auto_detect=True
    repository = InMemoryReflectionRepository()
    built: list[RecordingInspector] = []

    def factory(given_source: ReflectSource) -> RecordingInspector:
        inspector = RecordingInspector(source=given_source)
        built.append(inspector)
        return inspector

    with ReflectionSession(
        source,
        repository=repository,
        inspector_factory=factory,
    ) as session:
        assert session.table_names == ("alpha", "beta")
        table = session.table("alpha")

    assert table.name == "alpha"
    assert len(built) == 1
    assert built[0].source is source
    assert built[0].closed is True


def test_inspector_factory_does_not_touch_databricks_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The factory path must never call ``databricks_connection``."""

    def explode(source: ReflectSource) -> tuple[str, dict[str, object]]:
        raise AssertionError("databricks_connection must not be called")

    monkeypatch.setattr(
        "etlalchemy.reflect.inspector.databricks_connection",
        explode,
    )

    source = ReflectSource()
    repository = InMemoryReflectionRepository()
    session = ReflectionSession(
        source,
        repository=repository,
        inspector_factory=lambda given: RecordingInspector(source=given),
    )
    try:
        assert session.table("alpha").name == "alpha"
    finally:
        session.close()
