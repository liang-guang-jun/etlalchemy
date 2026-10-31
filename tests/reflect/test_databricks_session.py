"""Tests for the Databricks URL decoration a session performs."""

from __future__ import annotations

import etlalchemy.reflect.inspector as inspector_module
import pytest
import sqlalchemy as sa
from etlalchemy.reflect.inspector import ReflectionSession
from etlalchemy.reflect.repositories import InMemoryReflectionRepository
from etlalchemy.reflect.source import ReflectSource

from reflect.helpers import RecordingInspector

_BASE_URL = (
    "databricks://token:dapi-secret@adb-123.azuredatabricks.net:443"
    "?http_path=/sql/1.0/warehouses/abc"
)


def _capture_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> list[str]:
    """Replace the live inspector with one that records the URL it is given."""
    urls: list[str] = []
    inspector = RecordingInspector(names=())

    def make(url: str, connect_args: dict[str, object]) -> RecordingInspector:
        urls.append(url)
        return inspector

    monkeypatch.setattr(inspector_module, "LiveInspector", make)
    return urls


def test_databricks_url_gets_catalog_and_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The dialect reads the catalog from the URL, not from the schema argument."""
    monkeypatch.setattr(
        inspector_module,
        "databricks_connection",
        lambda source: (_BASE_URL, {}),
    )
    urls = _capture_urls(monkeypatch)

    session = ReflectionSession(
        ReflectSource(profile="DEFAULT"),
        repository=InMemoryReflectionRepository(),
        catalog="main",
        schema="default",
    )
    try:
        assert session.table_names == ()
    finally:
        session.close()

    assert len(urls) == 1
    url = sa.engine.make_url(urls[0])
    assert url.query["catalog"] == "main"
    assert url.query["schema"] == "default"
    assert url.query["http_path"] == "/sql/1.0/warehouses/abc"


def test_decorated_url_keeps_the_access_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The token must survive the rewrite; ``str(url)`` would mask it."""
    monkeypatch.setattr(
        inspector_module,
        "databricks_connection",
        lambda source: (_BASE_URL, {}),
    )
    urls = _capture_urls(monkeypatch)

    session = ReflectionSession(
        ReflectSource(profile="DEFAULT"),
        repository=InMemoryReflectionRepository(),
        catalog="main",
        schema="default",
    )
    try:
        assert session.table_names == ()
    finally:
        session.close()

    assert "***" not in urls[0]
    assert sa.engine.make_url(urls[0]).password == "dapi-secret"


def test_decorated_url_does_not_override_an_explicit_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A catalog already present in the URL wins over the session argument."""
    explicit = f"{_BASE_URL}&catalog=dev&schema=staging"
    monkeypatch.setattr(
        inspector_module,
        "databricks_connection",
        lambda source: (explicit, {}),
    )
    urls = _capture_urls(monkeypatch)

    session = ReflectionSession(
        ReflectSource(profile="DEFAULT"),
        repository=InMemoryReflectionRepository(),
        catalog="main",
        schema="default",
    )
    try:
        assert session.table_names == ()
    finally:
        session.close()

    url = sa.engine.make_url(urls[0])
    assert url.query["catalog"] == "dev"
    assert url.query["schema"] == "staging"


def test_other_dialects_keep_the_qualified_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-Databricks URL is untouched and keeps ``catalog.schema``."""
    urls = _capture_urls(monkeypatch)

    session = ReflectionSession(
        ReflectSource(connection_url="sqlite:///shop.db"),
        repository=InMemoryReflectionRepository(),
        catalog="cat",
        schema="sch",
    )
    try:
        assert session.table_names == ()
    finally:
        session.close()

    assert urls == ["sqlite:///shop.db"]
    assert session._effective_schema() == "cat.sch"
