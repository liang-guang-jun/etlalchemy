"""Tests for the vendored asynchronous infrastructure of eventsourcing.

The ``asyncio`` package of ``eventsourcing`` is not published on PyPI, so a copy
lives in ``etlalchemy/_vendor/eventsourcing/asyncio``. These tests pin the two
things that keep the copy wired in: every module goes through the vendored path,
and the official distribution contributes no ``asyncio`` package of its own.
"""

import importlib.util
from pathlib import Path

from eventsourcing.utils import Environment, resolve_topic

from etlalchemy._vendor.eventsourcing.asyncio.application import AsyncApplication
from etlalchemy._vendor.eventsourcing.asyncio.persistence import AsyncInfrastructureFactory
from etlalchemy._vendor.eventsourcing.asyncio.sqlalchemy import (
    AsyncSQLAlchemyApplicationRecorder,
    AsyncSQLAlchemyDatastore,
    AsyncSQLAlchemyFactory,
)
from etlalchemy.app.config.settings import PERSISTENCE_MODULE

VENDOR_PACKAGE = "etlalchemy._vendor.eventsourcing.asyncio"
"""Import prefix of the vendored copy."""

UPSTREAM_ASYNCIO = "eventsourcing" + ".asyncio"
"""Official path that does not exist; assembled so this module passes its own scan."""

SQLITE_MEMORY_URL = "sqlite+aiosqlite:///:memory:"
"""Database URL of the in-memory store used by the factory tests."""


def test_persistence_module_targets_the_vendored_sqlalchemy_module() -> None:
    """The configured persistence module resolves to the vendored package."""
    assert PERSISTENCE_MODULE == f"{VENDOR_PACKAGE}.sqlalchemy"

    module = resolve_topic(PERSISTENCE_MODULE)

    assert module.__name__ == PERSISTENCE_MODULE


def test_official_distribution_ships_no_asyncio_package() -> None:
    """The vendored copy is the only source of the asynchronous infrastructure."""
    assert importlib.util.find_spec(UPSTREAM_ASYNCIO) is None


def test_base_classes_are_the_vendored_ones() -> None:
    """Applications and datastores resolve to the vendored modules."""
    assert AsyncApplication.__module__ == f"{VENDOR_PACKAGE}.application"
    assert AsyncSQLAlchemyDatastore.__module__ == f"{VENDOR_PACKAGE}.sqlalchemy"


async def test_factory_falls_back_to_the_vendored_topic() -> None:
    """An environment without PERSISTENCE_MODULE still builds the vendored factory."""
    factory = AsyncInfrastructureFactory.construct({"SQLALCHEMY_URL": SQLITE_MEMORY_URL})
    try:
        assert isinstance(factory, AsyncSQLAlchemyFactory)
        assert type(factory).__module__ == f"{VENDOR_PACKAGE}.sqlalchemy"
    finally:
        await factory.aclose()


async def test_factory_derives_the_table_names_from_the_environment() -> None:
    """The vendored factory keeps the documented ``<app>_events`` table names."""
    factory = AsyncSQLAlchemyFactory(
        Environment("MyApp", {"SQLALCHEMY_URL": SQLITE_MEMORY_URL, "CREATE_TABLE": "no"})
    )
    try:
        recorder = factory.application_recorder()

        assert isinstance(recorder, AsyncSQLAlchemyApplicationRecorder)
        assert recorder.events_table.name == "myapp_events"
        assert factory.tracking_recorder().tracking_table.name == "myapp_tracking"
    finally:
        await factory.aclose()


def test_no_module_outside_the_vendor_tree_uses_the_upstream_topic() -> None:
    """Every reference reaches the async infrastructure through the vendored path."""
    root = Path(__file__).resolve().parents[2]
    sources = [
        *(root / "etlalchemy").rglob("*.py"),
        *(root / "tests").rglob("*.py"),
    ]

    offenders = [
        f"{path.relative_to(root)}:{number}"
        for path in sources
        if "_vendor" not in path.parts
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if UPSTREAM_ASYNCIO in line and VENDOR_PACKAGE not in line
    ]

    assert offenders == []
