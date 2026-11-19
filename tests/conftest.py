"""Fixtures shared by the asynchronous test suite."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from etlalchemy.catalog.application import CatalogApplication
from etlalchemy.catalog.projection.sqlalchemy import SQLAlchemyCatalogView
from eventsourcing.asyncio.sqlalchemy import AsyncSQLAlchemyDatastore

from tests.support import async_env, sqlite_url


@pytest.fixture
def app_env(tmp_path: Path) -> dict[str, str]:
    """Returns an eventsourcing environment backed by a temporary SQLite file."""
    return async_env(sqlite_url(tmp_path / "events.db"))


@pytest.fixture
async def datastore(tmp_path: Path) -> AsyncIterator[AsyncSQLAlchemyDatastore]:
    """Returns an async datastore backed by a temporary SQLite file."""
    store = AsyncSQLAlchemyDatastore(sqlite_url(tmp_path / "view.db"))
    try:
        yield store
    finally:
        await store.close()


@pytest.fixture
async def catalog_app(app_env: dict[str, str]) -> AsyncIterator[CatalogApplication]:
    """Returns a started catalog application on a temporary event store."""
    async with CatalogApplication(env=app_env) as app:
        yield app


@pytest.fixture
async def catalog_view(
    datastore: AsyncSQLAlchemyDatastore,
) -> AsyncIterator[SQLAlchemyCatalogView]:
    """Returns an empty catalog view whose tables exist."""
    view = SQLAlchemyCatalogView(
        datastore=datastore,
        tracking_table=datastore.create_tracking_table("catalog_projection_tracking"),
    )
    await view.create_table()
    yield view
