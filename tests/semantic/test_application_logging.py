"""Tests that the semantic use cases emit structured logs."""

from __future__ import annotations

import pytest
from structlog.testing import capture_logs

from etlalchemy.semantic.application import ModelApplication
from etlalchemy.shared.logging import reset_logging
from tests.semantic.support import FakeCatalogView


@pytest.fixture(autouse=True)
def _fresh_loggers() -> None:
    """Drops cached loggers so ``capture_logs`` sees the application output."""
    reset_logging()


async def test_create_model_logs_start_and_done(model_app: ModelApplication) -> None:
    """The create use case logs the command name and the new id."""
    with capture_logs() as logs:
        model_id = await model_app.create_model("sales")

    assert [entry["event"] for entry in logs] == [
        "semantic.model.create start",
        "semantic.model.create done",
    ]
    assert logs[0]["name"] == "sales"
    assert logs[1]["model_id"] == str(model_id)


async def test_add_entity_logs_the_entity_and_its_table(
    model_app: ModelApplication,
    catalog_view: FakeCatalogView,
) -> None:
    """The entity command logs what it adds."""
    model_id = await model_app.create_model("sales")
    table_id = catalog_view.add_table("orders", "id")

    with capture_logs() as logs:
        await model_app.add_entity(model_id, "orders", table_id)

    assert [entry["event"] for entry in logs] == [
        "semantic.entity.add start",
        "semantic.entity.add done",
    ]
    assert logs[0]["entity"] == "orders"
    assert logs[0]["table_id"] == str(table_id)
    assert logs[1]["model_id"] == str(model_id)


async def test_rename_logs_both_names(
    model_app: ModelApplication,
    catalog_view: FakeCatalogView,
) -> None:
    """The rename log carries the old and the new name."""
    model_id = await model_app.create_model("sales")
    await model_app.add_entity(model_id, "customers", catalog_view.add_table("customers", "id"))

    with capture_logs() as logs:
        await model_app.rename_entity(model_id, "customers", "clients")

    assert logs[0]["event"] == "semantic.entity.rename start"
    assert (logs[0]["old_name"], logs[0]["new_name"]) == ("customers", "clients")
    assert logs[-1]["event"] == "semantic.entity.rename done"
    assert logs[-1]["name"] == "clients"


async def test_reads_log_at_debug_level(model_app: ModelApplication) -> None:
    """Reading a model leaves a debug trail."""
    model_id = await model_app.create_model("sales")

    with capture_logs() as logs:
        await model_app.get_model(model_id)

    assert [entry["event"] for entry in logs] == [
        "semantic.model.get start",
        "semantic.model.get done",
    ]
    assert logs[0]["log_level"] == "debug"
