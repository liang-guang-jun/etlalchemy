"""Tests for the ingestion projection runner."""

from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from etlalchemy.ingestion.aggregates.connection import SourceConnection
from etlalchemy.ingestion.aggregates.import_run import ImportRun
from etlalchemy.ingestion.projection.projection import (
    IngestionEventApplication,
    run_ingestion_projection,
)
from etlalchemy.shared.logging import reset_logging
from structlog.testing import capture_logs

from tests.support import async_env, sqlite_url


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    """Returns an environment backed by a temporary SQLite event store."""
    return async_env(sqlite_url(tmp_path / "events.db"))


async def test_projection_materialises_connections_and_runs(env: dict[str, str]) -> None:
    """The runner keeps the view in step with the application's notification log."""
    async with IngestionEventApplication(env=env) as app:
        connection = SourceConnection(
            name="warehouse",
            kind="databricks",
            endpoint="https://example.test",
            token="s3cr3t",
            default_catalog="main",
            options={"warehouse_id": "abc"},
        )
        await app.save(connection)
        run = ImportRun(
            connection_id=connection.id,
            target_catalog_id=uuid4(),
            source_catalog="src",
            include_schemas=["sales"],
            include_tables={"sales": ["orders"]},
            schema_mapping={"sales": "sales_raw"},
        )
        await app.save(run)
        run.succeed(1, 2, 3)
        await app.save(run)
        failed_run = ImportRun(connection_id=connection.id, target_catalog_id=uuid4())
        await app.save(failed_run)
        failed_run.fail("boom", 1, 0, 0)
        await app.save(failed_run)
        last = await app.recorder.max_notification_id()
    assert last is not None

    async with run_ingestion_projection(env) as runner:
        await runner.wait(last, timeout=5.0)
        view: Any = runner.view

        row = await view.get_connection(connection.id)
        assert row is not None
        assert row.name == "warehouse"
        assert row.kind == "databricks"
        assert row.endpoint == "https://example.test"
        assert row.credential_ref is None
        assert row.has_inline_credential is True
        assert row.default_catalog == "main"
        assert row.options == {"warehouse_id": "abc"}
        assert await view.find_connection_by_name("warehouse") is not None
        assert [candidate.name for candidate in await view.list_connections()] == ["warehouse"]

        succeeded = await view.get_import_run(run.id)
        assert succeeded is not None
        assert succeeded.status == "succeeded"
        assert succeeded.include_schemas == ["sales"]
        assert succeeded.include_tables == {"sales": ["orders"]}
        assert succeeded.schema_mapping == {"sales": "sales_raw"}
        assert (succeeded.schema_count, succeeded.table_count, succeeded.field_count) == (1, 2, 3)

        failed = await view.get_import_run(failed_run.id)
        assert failed is not None
        assert failed.status == "failed"
        assert failed.error == "boom"
        assert await view.max_tracking_id("ingestion_application") == last


async def test_projection_applies_changes_rotation_and_discard(env: dict[str, str]) -> None:
    """Renames, credential rotation and soft deletes reach the read model."""
    async with IngestionEventApplication(env=env) as app:
        connection = SourceConnection(
            name="warehouse",
            kind="databricks",
            endpoint="https://example.test",
            credential_ref="env:DBX_TOKEN",
        )
        await app.save(connection)
        connection.change(name="renamed", options={"warehouse_id": "xyz"})
        await app.save(connection)
        connection.rotate_credential(token="s3cr3t")
        await app.save(connection)
        connection.discard()
        await app.save(connection)
        last = await app.recorder.max_notification_id()
    assert last is not None

    async with run_ingestion_projection(env) as runner:
        await runner.wait(last, timeout=5.0)
        view: Any = runner.view

        assert await view.get_connection(connection.id) is None
        assert await view.find_connection_by_name("warehouse") is None
        assert await view.find_connection_by_name("renamed") is None
        assert await view.list_connections() == []
        assert await view.max_tracking_id("ingestion_application") == last


async def test_projection_records_an_abandoned_run(env: dict[str, str]) -> None:
    """Abandoned runs reach the view with their reason."""
    async with IngestionEventApplication(env=env) as app:
        run = ImportRun(connection_id=uuid4(), target_catalog_id=uuid4())
        await app.save(run)
        run.abandon("process crashed")
        await app.save(run)
        last = await app.recorder.max_notification_id()
    assert last is not None

    async with run_ingestion_projection(env) as runner:
        await runner.wait(last, timeout=5.0)
        view: Any = runner.view

        row = await view.get_import_run(run.id)
        assert row is not None
        assert row.status == "abandoned"
        assert row.error == "process crashed"
        assert await view.max_tracking_id("ingestion_application") == last


async def test_runner_logs_its_start(env: dict[str, str]) -> None:
    """Starting the runner reports the projection and the view it fills."""
    reset_logging()

    with capture_logs() as logs:
        async with run_ingestion_projection(env):
            pass

    started = next(entry for entry in logs if entry["event"] == "projection.runner.started")
    assert started["application"] == "ingestion_application"
    assert started["projection"] == "ingestion_projection"
    assert started["view"] == "SQLAlchemyIngestionView"
