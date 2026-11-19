"""Shared fixtures for the LLM provider context tests."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from etlalchemy.llm_config.application import LlmConfigApplication
from etlalchemy.llm_config.projection.sqlalchemy import SQLAlchemyLlmProviderView
from eventsourcing.asyncio.sqlalchemy import AsyncSQLAlchemyDatastore

from tests.llm_config.support import FakeAuthorization, FakeSecrets


@pytest.fixture
def authorization() -> FakeAuthorization:
    """Returns an empty fake authorization port."""
    return FakeAuthorization()


@pytest.fixture
def secrets() -> FakeSecrets:
    """Returns an empty fake secret resolver."""
    return FakeSecrets()


@pytest.fixture
async def provider_view(
    datastore: AsyncSQLAlchemyDatastore,
) -> AsyncIterator[SQLAlchemyLlmProviderView]:
    """Returns an empty LLM provider view whose tables exist."""
    view = SQLAlchemyLlmProviderView(
        datastore=datastore,
        tracking_table=datastore.create_tracking_table("llm_config_projection_tracking"),
    )
    await view.create_table()
    yield view


@pytest.fixture
async def llm_app(
    authorization: FakeAuthorization,
    secrets: FakeSecrets,
    provider_view: SQLAlchemyLlmProviderView,
    app_env: dict[str, str],
) -> AsyncIterator[LlmConfigApplication]:
    """Returns a started LLM provider application on a temporary event store."""
    application = LlmConfigApplication(
        view=provider_view,
        iam=authorization,
        secrets=secrets,
        env=app_env,
    )
    async with application:
        yield application
