"""Tests for the catalog projection runner."""

from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from etlalchemy.catalog.application import CatalogApplication
from etlalchemy.catalog.projection.projection import run_catalog_projection
from etlalchemy.shared.logging import reset_logging
from structlog.testing import capture_logs

from tests.support import async_env, sqlite_url


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    """Returns an environment backed by a temporary SQLite event store."""
    return async_env(sqlite_url(tmp_path / "events.db"))


async def write_catalog(env: dict[str, str]) -> tuple[UUID, UUID, UUID, int]:
    """Writes a small catalog through the application and returns its ids."""
    async with CatalogApplication(env=env) as app:
        catalog_id = await app.create_catalog("analytics")
        schema_id = await app.create_schema(catalog_id, "sales", "Sales data")
        table_id = await app.add_table(catalog_id, "sales", "orders")
        await app.add_field(catalog_id, "sales", "orders", "id", "integer", nullable=False)
        await app.add_field(catalog_id, "sales", "orders", "note", "text")
        await app.change_field(catalog_id, "sales", "orders", "note", data_type="varchar")
        await app.remove_field(catalog_id, "sales", "orders", "note")
        last = await app.recorder.max_notification_id()
    assert last is not None
    return catalog_id, schema_id, table_id, last


async def test_projection_materialises_the_catalog(env: dict[str, str]) -> None:
    """The runner keeps the view in step with the application's notification log."""
    catalog_id, schema_id, table_id, last = await write_catalog(env)

    async with run_catalog_projection(env) as runner:
        await runner.wait(last, timeout=5.0)
        view: Any = runner.view

        assert await view.find_schema_id(catalog_id, "sales") == schema_id
        assert await view.find_table_id(schema_id, "orders") == table_id
        catalog = await view.get_catalog(catalog_id)
        assert catalog is not None
        assert (catalog.name, catalog.description) == ("analytics", "")
        assert [row.catalog_id for row in await view.list_catalogs()] == [catalog_id]
        fields = await view.list_fields(table_id)
        assert [(f.name, str(f.data_type), f.nullable) for f in fields] == [
            ("id", "integer", False)
        ]
        assert await view.max_tracking_id("catalog_application") == last


async def test_projection_resumes_from_the_recorded_tracking(env: dict[str, str]) -> None:
    """A restarted runner continues after the last tracked notification."""
    catalog_id, _, table_id, last = await write_catalog(env)

    async with run_catalog_projection(env) as runner:
        await runner.wait(last, timeout=5.0)

    async with CatalogApplication(env=env) as app:
        await app.add_field(
            catalog_id, "sales", "orders", "created_at", "timestamp", nullable=False
        )
        new_last = await app.recorder.max_notification_id()
    assert new_last is not None

    async with run_catalog_projection(env) as runner:
        await runner.wait(new_last, timeout=5.0)
        view: Any = runner.view

        assert [f.name for f in await view.list_fields(table_id)] == ["created_at", "id"]
        assert await view.max_tracking_id("catalog_application") == new_last


async def write_changes(env: dict[str, str]) -> tuple[UUID, UUID, UUID, int]:
    """Writes renames and changes through the application and returns its ids."""
    async with CatalogApplication(env=env) as app:
        catalog_id = await app.create_catalog("analytics")
        schema_id = await app.create_schema(catalog_id, "sales", "Sales data")
        table_id = await app.add_table(catalog_id, "sales", "orders")
        await app.add_field(catalog_id, "sales", "orders", "id", "integer", nullable=False)
        await app.change_table(catalog_id, "sales", "orders", new_name="purchases")
        await app.add_field(catalog_id, "sales", "purchases", "note", "text")
        await app.rename_field(catalog_id, "sales", "purchases", "note", "comment")
        await app.change_schema(catalog_id, "sales", new_name="revenue", new_description="Revenue")
        await app.change_catalog(catalog_id, name="warehouse")
        last = await app.recorder.max_notification_id()
    assert last is not None
    return catalog_id, schema_id, table_id, last


async def test_projection_applies_changes_and_renames(env: dict[str, str]) -> None:
    """Renames and changes reach the read model."""
    catalog_id, schema_id, table_id, last = await write_changes(env)

    async with run_catalog_projection(env) as runner:
        await runner.wait(last, timeout=5.0)
        view: Any = runner.view

        catalog = await view.get_catalog(catalog_id)
        assert catalog is not None
        assert catalog.name == "warehouse"
        assert await view.find_schema_id(catalog_id, "revenue") == schema_id
        assert await view.find_table_id(schema_id, "purchases") == table_id
        schema = await view.get_schema(schema_id)
        assert schema is not None
        assert (schema.name, schema.description) == ("revenue", "Revenue")
        table = await view.get_table(table_id)
        assert table is not None
        assert table.name == "purchases"
        assert [row.name for row in await view.list_fields(table_id)] == ["comment", "id"]
        assert [row.table_name for row in await view.search_fields("comment")] == ["purchases"]
        assert await view.max_tracking_id("catalog_application") == last


async def test_projection_discards_a_table_and_a_schema(env: dict[str, str]) -> None:
    """Discarding children hides them from the read model."""
    async with CatalogApplication(env=env) as app:
        catalog_id = await app.create_catalog("analytics")
        schema_id = await app.create_schema(catalog_id, "sales")
        table_id = await app.add_table(catalog_id, "sales", "orders")
        await app.add_field(catalog_id, "sales", "orders", "id", "integer", nullable=False)
        await app.discard_table(catalog_id, "sales", "orders")
        await app.discard_schema(catalog_id, "sales")
        last = await app.recorder.max_notification_id()
    assert last is not None

    async with run_catalog_projection(env) as runner:
        await runner.wait(last, timeout=5.0)
        view: Any = runner.view

        assert await view.list_tables(schema_id) == []
        assert await view.list_fields(table_id) == []
        assert await view.list_schemas(catalog_id) == []
        assert await view.get_catalog(catalog_id) is not None
        assert await view.max_tracking_id("catalog_application") == last


async def test_projection_discards_the_whole_catalog(env: dict[str, str]) -> None:
    """Discarding a catalog hides the whole subtree."""
    async with CatalogApplication(env=env) as app:
        catalog_id = await app.create_catalog("analytics")
        await app.create_schema(catalog_id, "sales")
        await app.add_table(catalog_id, "sales", "orders")
        await app.add_field(catalog_id, "sales", "orders", "id", "integer", nullable=False)
        await app.discard_catalog(catalog_id)
        last = await app.recorder.max_notification_id()
    assert last is not None

    async with run_catalog_projection(env) as runner:
        await runner.wait(last, timeout=5.0)
        view: Any = runner.view

        assert await view.get_catalog(catalog_id) is None
        assert await view.list_catalogs() == []
        assert await view.search_fields("orders") == []
        assert await view.max_tracking_id("catalog_application") == last


async def test_runner_logs_its_start(env: dict[str, str]) -> None:
    """Starting the runner reports the projection and the view it fills."""
    reset_logging()

    with capture_logs() as logs:
        async with run_catalog_projection(env):
            pass

    started = next(entry for entry in logs if entry["event"] == "projection.runner.started")
    assert started["application"] == "catalog_application"
    assert started["projection"] == "catalog_projection"
    assert started["view"] == "SQLAlchemyCatalogView"
