"""Tests for the FastAPI lifespan."""

import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from dependency_injector import providers
from etlalchemy.app.api.app import create_app
from fastapi.testclient import TestClient


class _FakeRunner:
    """Stand-in projection runner that records its shutdown."""

    def __init__(self) -> None:
        self.stopped = False

    def stop(self) -> None:
        """Records that the resource has been shut down."""
        self.stopped = True


def _fake_projection_resource(fake: _FakeRunner) -> Iterator[_FakeRunner]:
    yield fake
    fake.stop()


def test_lifespan_creates_the_read_model(config_dir: Path) -> None:
    """Starting the application creates the view and tracking tables."""
    app = create_app()
    container: Any = app.container
    sqlite_path = container.settings().database.sqlite_path

    with TestClient(app) as client:
        assert client.get("/catalog/search", params={"term": "x"}).status_code == 200

    connection = sqlite3.connect(sqlite_path)
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    finally:
        connection.close()
    assert {
        "catalog_catalogs",
        "catalog_schemas",
        "catalog_tables",
        "catalog_fields",
        "catalog_application_events",
        "catalog_projection_tracking",
        "ingestion_connections",
        "ingestion_import_runs",
        "ingestion_application_events",
        "ingestion_projection_tracking",
        "vocabulary_domains",
        "vocabulary_terms",
        "vocabulary_term_aliases",
        "vocabulary_term_links",
        "vocabulary_application_events",
        "vocabulary_projection_tracking",
        "semantic_models",
        "semantic_entities",
        "semantic_relationships",
        "semantic_relationship_fields",
        "semantic_diagrams",
        "semantic_nodes",
        "semantic_application_events",
        "semantic_projection_tracking",
    } <= tables


def test_lifespan_stops_the_projection_resource(config_dir: Path) -> None:
    """Shutting down the application stops the projection resource."""
    fake = _FakeRunner()
    app = create_app()
    app.container.catalog_projection_runner.override(
        providers.Resource(_fake_projection_resource, fake=fake)
    )

    with TestClient(app):
        pass

    assert fake.stopped is True
