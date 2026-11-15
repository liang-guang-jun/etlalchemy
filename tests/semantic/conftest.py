"""Shared fixtures for the semantic context tests."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from eventsourcing.asyncio.sqlalchemy import AsyncSQLAlchemyDatastore

from etlalchemy.semantic.application import ModelApplication
from etlalchemy.semantic.projection.sqlalchemy import SQLAlchemySemanticView
from tests.semantic.support import FakeCatalogView


@pytest.fixture
def catalog_view() -> FakeCatalogView:
    """Returns an empty fake catalog view."""
    return FakeCatalogView()


@pytest.fixture
async def model_app(
    catalog_view: FakeCatalogView,
    app_env: dict[str, str],
) -> AsyncIterator[ModelApplication]:
    """Returns a started semantic application bound to the fake catalog view."""
    async with ModelApplication(catalog_view=catalog_view, env=app_env) as application:
        yield application


@pytest.fixture
async def semantic_view(
    datastore: AsyncSQLAlchemyDatastore,
) -> AsyncIterator[SQLAlchemySemanticView]:
    """Returns an empty semantic view whose tables exist."""
    view = SQLAlchemySemanticView(
        datastore=datastore,
        tracking_table=datastore.create_tracking_table("semantic_projection_tracking"),
    )
    await view.create_table()
    yield view
