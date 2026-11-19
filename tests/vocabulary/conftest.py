"""Shared fixtures for the vocabulary context tests."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from etlalchemy.vocabulary.application import VocabularyApplication
from etlalchemy.vocabulary.projection.sqlalchemy import SQLAlchemyVocabularyView
from eventsourcing.asyncio.sqlalchemy import AsyncSQLAlchemyDatastore

from tests.vocabulary.support import FakeCatalogView


@pytest.fixture
def catalog_view() -> FakeCatalogView:
    """Returns an empty fake catalog view."""
    return FakeCatalogView()


@pytest.fixture
async def vocabulary_app(
    catalog_view: FakeCatalogView,
    app_env: dict[str, str],
) -> AsyncIterator[VocabularyApplication]:
    """Returns a started vocabulary application bound to the fake catalog view."""
    async with VocabularyApplication(catalog_view=catalog_view, env=app_env) as application:
        yield application


@pytest.fixture
async def vocabulary_view(
    datastore: AsyncSQLAlchemyDatastore,
) -> AsyncIterator[SQLAlchemyVocabularyView]:
    """Returns an empty vocabulary view whose tables exist."""
    view = SQLAlchemyVocabularyView(
        datastore=datastore,
        tracking_table=datastore.create_tracking_table("vocabulary_projection_tracking"),
    )
    await view.create_table()
    yield view
