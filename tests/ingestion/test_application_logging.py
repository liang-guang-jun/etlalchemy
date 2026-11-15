"""Tests that the ingestion use cases emit structured logs."""

from __future__ import annotations

from uuid import UUID

import pytest
import structlog
from structlog.testing import capture_logs

from etlalchemy.ingestion import IngestionApplication
from etlalchemy.ingestion.ports.data_source import ColumnInfo
from etlalchemy.shared.logging import reset_logging
from tests.ingestion.support import FakeSource, RecordingCatalogApplication


@pytest.fixture(autouse=True)
def _fresh_loggers() -> None:
    """Drops cached loggers so ``capture_logs`` sees the application output."""
    reset_logging()


async def create_connection(application: IngestionApplication, **overrides: object) -> UUID:
    """Creates a connection with defaults suitable for the fake factory."""
    values: dict[str, object] = {
        "name": "warehouse",
        "kind": "fake",
        "endpoint": "https://example.test",
        "token": "s3cr3t",
    }
    values.update(overrides)
    return await application.create_connection(**values)  # type: ignore[arg-type]


def source_tree() -> dict[str, dict[str, dict[str, list[ColumnInfo]]]]:
    """Returns a one-catalog, one-schema, one-table source tree."""
    return {
        "src": {
            "sales": {
                "orders": [
                    ColumnInfo(name="id", raw_type="BIGINT", nullable=False),
                ]
            }
        }
    }


async def test_create_connection_logs_without_the_secret(
    application: IngestionApplication,
) -> None:
    """The credential is described, never logged."""
    with capture_logs() as logs:
        connection_id = await create_connection(application)

    start = next(entry for entry in logs if entry["event"] == "ingestion.connection.create start")
    assert start["credential"] == "inline"
    assert "s3cr3t" not in repr(logs)
    done = next(entry for entry in logs if entry["event"] == "ingestion.connection.create done")
    assert done["connection_id"] == str(connection_id)


async def test_rotate_credential_logs_the_reference_only(
    application: IngestionApplication,
) -> None:
    """Rotating a credential logs its kind, not its value."""
    connection_id = await create_connection(application)

    with capture_logs() as logs:
        await application.rotate_credential(connection_id, credential_ref="env:WAREHOUSE_TOKEN")

    start = next(entry for entry in logs if entry["event"] == "ingestion.credential.rotate start")
    assert start["credential"] == "env:WAREHOUSE_TOKEN"


async def test_import_from_binds_the_run_context(
    application: IngestionApplication,
    catalog: RecordingCatalogApplication,
    source: FakeSource,
) -> None:
    """The import logs carry the run id bound with ``bound_context``."""
    catalog_id = await catalog.create_catalog("target")
    connection_id = await create_connection(application)
    source.catalogs = source_tree()

    with capture_logs(processors=[structlog.contextvars.merge_contextvars]) as logs:
        run_id = await application.import_from(connection_id, catalog_id, source_catalog="src")

    done = next(entry for entry in logs if entry["event"] == "ingestion.import done")
    assert done["run_id"] == str(run_id)
    assert done["connection_id"] == str(connection_id)
    assert done["target_catalog_id"] == str(catalog_id)
    assert done["schemas"] == 1
    assert done["tables"] == 1


async def test_failed_import_logs_the_error(
    application: IngestionApplication,
    catalog: RecordingCatalogApplication,
    source: FakeSource,
) -> None:
    """A failing import logs the failure with its traceback and re-raises."""
    catalog_id = await catalog.create_catalog("target")
    connection_id = await create_connection(application)
    source.catalogs = source_tree()
    source.fail_with = "source exploded"

    with capture_logs() as logs, pytest.raises(RuntimeError, match="source exploded"):
        await application.import_from(connection_id, catalog_id, source_catalog="src")

    failed = next(entry for entry in logs if entry["event"] == "ingestion.import failed")
    assert failed["log_level"] == "error"


async def test_inspect_source_logs_the_inspected_level(
    application: IngestionApplication,
    source: FakeSource,
) -> None:
    """An inspection logs the node it walked and how many items it returned."""
    connection_id = await create_connection(application)
    source.catalogs = source_tree()

    with capture_logs() as logs:
        await application.inspect_source(connection_id)

    done = next(entry for entry in logs if entry["event"] == "ingestion.inspect done")
    assert done["node"] == "catalogs"
    assert done["items"] == 1
