"""Tests that the catalog use cases emit structured logs."""

from __future__ import annotations

import pytest
from etlalchemy.catalog import CatalogApplication
from etlalchemy.catalog.aggregates.errors import UnknownSchemaError
from etlalchemy.shared.logging import reset_logging
from structlog.testing import capture_logs


@pytest.fixture(autouse=True)
def _fresh_loggers() -> None:
    """Drops cached loggers so ``capture_logs`` sees the application output."""
    reset_logging()


async def test_create_catalog_logs_start_and_done(catalog_app: CatalogApplication) -> None:
    """The create use case logs the command name and the new id."""
    app = catalog_app

    with capture_logs() as logs:
        catalog_id = await app.create_catalog("analytics")

    assert [entry["event"] for entry in logs] == ["catalog.create start", "catalog.create done"]
    assert logs[0]["name"] == "analytics"
    assert logs[1]["catalog_id"] == str(catalog_id)


async def test_change_catalog_logs_the_command_and_the_nested_read(catalog_app: CatalogApplication) -> None:
    """A write logs its own start/done around the debug logs of the read it makes."""
    app = catalog_app
    catalog_id = await app.create_catalog("analytics")

    with capture_logs() as logs:
        await app.change_catalog(catalog_id, name="orders")

    events = [entry["event"] for entry in logs]
    assert events[0] == "catalog.change start"
    assert "catalog.get start" in events
    assert events[-1] == "catalog.change done"


async def test_field_use_case_logs_the_payload(catalog_app: CatalogApplication) -> None:
    """The field logs carry the field name, type and nullability."""
    app = catalog_app
    catalog_id = await app.create_catalog("analytics")
    schema_id = await app.create_schema(catalog_id, "sales")
    table_id = await app.add_table(catalog_id, schema_id, "orders")

    with capture_logs() as logs:
        await app.add_field(catalog_id, schema_id, table_id, "amount", "decimal(10,2)", False)

    start = next(entry for entry in logs if entry["event"] == "catalog.field.add start")
    assert start["field"] == "amount"
    assert start["data_type"] == "decimal(10,2)"
    assert start["nullable"] is False


async def test_unknown_schema_is_logged_before_raising(catalog_app: CatalogApplication) -> None:
    """The lookup helper logs at debug level and then raises."""
    app = catalog_app
    catalog_id = await app.create_catalog("analytics")

    with capture_logs() as logs, pytest.raises(UnknownSchemaError):
        await app.get_schema(catalog_id, "missing")

    assert "catalog.schema.not_found" in [entry["event"] for entry in logs]
