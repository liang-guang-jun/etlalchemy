"""Shared fixtures for the ingestion context tests."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from etlalchemy.ingestion.adapters.secrets_composite import CompositeSecretsResolver
from etlalchemy.ingestion.adapters.secrets_env import EnvSecretsProvider
from etlalchemy.ingestion.application import IngestionApplication
from tests.ingestion.support import (
    FakeCatalogView,
    FakeConnectionsView,
    FakeSource,
    FakeSourceFactory,
    RecordingCatalogApplication,
)


@pytest.fixture
def catalog_view() -> FakeCatalogView:
    """Returns an empty fake catalog view."""
    return FakeCatalogView()


@pytest.fixture
async def catalog(
    catalog_view: FakeCatalogView,
    app_env: dict[str, str],
) -> AsyncIterator[RecordingCatalogApplication]:
    """Returns a started catalog application bound to the fake view."""
    application = RecordingCatalogApplication(catalog_view, env=app_env)
    async with application:
        yield application


@pytest.fixture
def source() -> FakeSource:
    """Returns an empty fake data source."""
    return FakeSource()


@pytest.fixture
def factory(source: FakeSource) -> FakeSourceFactory:
    """Returns a fake factory that builds the shared source."""
    return FakeSourceFactory(source)


@pytest.fixture
def connections_view() -> FakeConnectionsView:
    """Returns an empty fake connection read model."""
    return FakeConnectionsView()


@pytest.fixture
async def application(
    catalog: RecordingCatalogApplication,
    catalog_view: FakeCatalogView,
    connections_view: FakeConnectionsView,
    factory: FakeSourceFactory,
    app_env: dict[str, str],
) -> AsyncIterator[IngestionApplication]:
    """Returns a started ingestion application wired with fakes."""
    ingestion = IngestionApplication(
        catalog=catalog,
        catalog_view=catalog_view,
        connections_view=connections_view,
        factories={factory.kind: factory},
        secrets=CompositeSecretsResolver({"env": EnvSecretsProvider()}),
        env=app_env,
    )
    async with ingestion:
        yield ingestion
