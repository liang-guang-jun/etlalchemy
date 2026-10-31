"""_effective_schema builds the schema argument without importing reflector."""

from __future__ import annotations

import sys

import etlalchemy.reflect.inspector as inspector_module
import pytest
from etlalchemy.reflect.inspector import ReflectionSession
from etlalchemy.reflect.repositories import InMemoryReflectionRepository
from etlalchemy.reflect.source import ReflectSource
from reflect.helpers import RecordingInspector

_DATABRICKS_URL = (
    "databricks://token:dapi-secret@adb-123.azuredatabricks.net:443"
    "?http_path=/sql/1.0/warehouses/abc"
)


def test_effective_schema_joins_catalog_and_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A catalog and a schema become one dotted schema argument."""
    inspector = RecordingInspector(names=())
    monkeypatch.setattr(
        "etlalchemy.reflect.inspector.LiveInspector",
        lambda url, connect_args: inspector,
    )
    session = ReflectionSession(
        ReflectSource(connection_url="sqlite://"),
        repository=InMemoryReflectionRepository(),
        catalog="cat",
        schema="sch",
    )
    try:
        assert session.table_names == ()
    finally:
        session.close()

    assert inspector.schemas == ["cat.sch"]


def test_effective_schema_uses_only_schema_when_catalog_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without a catalog the schema is used as is."""
    inspector = RecordingInspector(names=())
    monkeypatch.setattr(
        "etlalchemy.reflect.inspector.LiveInspector",
        lambda url, connect_args: inspector,
    )
    session = ReflectionSession(
        ReflectSource(connection_url="sqlite://"),
        repository=InMemoryReflectionRepository(),
        schema="sch",
    )
    try:
        assert session.table_names == ()
    finally:
        session.close()

    assert inspector.schemas == ["sch"]


def test_effective_schema_is_the_bare_schema_for_databricks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Databricks fixes the catalog in the URL, so the schema stays unqualified."""
    monkeypatch.setattr(
        inspector_module,
        "databricks_connection",
        lambda source: (_DATABRICKS_URL, {}),
    )
    session = ReflectionSession(
        ReflectSource(profile="DEFAULT"),
        repository=InMemoryReflectionRepository(),
        catalog="main",
        schema="default",
    )

    assert session._effective_schema() == "default"


def test_effective_schema_does_not_import_reflector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Building the schema argument must not pull in the reflector module."""
    monkeypatch.setattr(
        "etlalchemy.reflect.inspector.LiveInspector",
        lambda url, connect_args: RecordingInspector(names=()),
    )
    sys.modules.pop("etlalchemy.reflect.reflector", None)
    session = ReflectionSession(
        ReflectSource(connection_url="sqlite://"),
        repository=InMemoryReflectionRepository(),
        catalog="cat",
        schema="sch",
    )
    try:
        assert session._effective_schema() == "cat.sch"
    finally:
        session.close()

    assert "etlalchemy.reflect.reflector" not in sys.modules
