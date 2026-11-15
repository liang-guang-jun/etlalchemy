"""Tests for the semantic projection runner."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
import sqlalchemy as sa

from etlalchemy._vendor.eventsourcing.asyncio.sqlalchemy import AsyncSQLAlchemyDatastore
from etlalchemy.semantic.aggregates.types import ALL_DIAGRAM, Cardinality, FieldRef, FilterDirection
from etlalchemy.semantic.application import ModelApplication
from etlalchemy.semantic.projection.projection import run_semantic_projection
from etlalchemy.semantic.projection.sqlalchemy import SQLAlchemySemanticView
from etlalchemy.semantic.projection.tables import metadata as view_metadata
from tests.semantic.support import FakeCatalogView
from tests.support import async_env, sqlite_url


@pytest.fixture
def events_url(tmp_path: Path) -> str:
    """Returns the SQLite URL used by the event store and the view."""
    return sqlite_url(tmp_path / "events.db")


@pytest.fixture
def env(events_url: str) -> dict[str, str]:
    """Returns an environment backed by a temporary SQLite event store."""
    return async_env(events_url)


async def write_model(
    env: dict[str, str],
    catalog_view: FakeCatalogView,
) -> tuple[UUID, UUID, int]:
    """Writes a small model through the application and returns its ids."""
    customers = catalog_view.add_table("customers", "id")
    orders = catalog_view.add_table("orders", "id", "customer_id")
    async with ModelApplication(catalog_view=catalog_view, env=env) as app:
        model_id = await app.create_model("sales", "Revenue model")
        await app.add_entity(model_id, "customers", customers)
        await app.add_entity(model_id, "orders", orders)
        relationship_id = await app.add_relationship(
            model_id,
            [FieldRef(entity="customers", field="id")],
            [FieldRef(entity="orders", field="customer_id")],
            Cardinality.ONE_TO_MANY,
            FilterDirection.BOTH,
        )
        await app.add_diagram(model_id, "detail", 1)
        await app.place_node(model_id, "detail", "orders", 5.0, 6.0)
        await app.move_node(model_id, "detail", "orders", 7.0, 8.0)
        await app.rename_entity(model_id, "customers", "clients")
        last = await app.recorder.max_notification_id()
    assert last is not None
    return model_id, relationship_id, last


async def test_projection_materialises_the_model(
    env: dict[str, str],
    catalog_view: FakeCatalogView,
) -> None:
    """The runner keeps the view in step with the application's notification log."""
    model_id, relationship_id, last = await write_model(env, catalog_view)

    async with run_semantic_projection(env) as runner:
        await runner.wait(last, timeout=5.0)
        view: Any = runner.view

        model = await view.get_model(model_id)
        assert model is not None
        assert (model.name, model.description) == ("sales", "Revenue model")
        entities = await view.list_entities(model_id)
        assert [entity.name for entity in entities] == ["clients", "orders"]
        assert all(entity.table_id in catalog_view.tables for entity in entities)
        relationship = await view.get_relationship(relationship_id)
        assert relationship is not None
        assert relationship.from_refs == [("clients", "id")]
        assert relationship.to_refs == [("orders", "customer_id")]
        assert (relationship.cardinality, relationship.filter_direction) == (
            "one_to_many",
            "both",
        )
        assert [row.name for row in await view.list_diagrams(model_id)] == [
            ALL_DIAGRAM,
            "detail",
        ]
        all_nodes = await view.list_nodes(model_id, ALL_DIAGRAM)
        assert [(node.entity_name, node.x, node.y) for node in all_nodes] == [
            ("clients", 0.0, 0.0),
            ("orders", 40.0, 40.0),
        ]
        detail_nodes = await view.list_nodes(model_id, "detail")
        assert [(node.entity_name, node.x, node.y) for node in detail_nodes] == [
            ("orders", 7.0, 8.0)
        ]
        assert await view.max_tracking_id("semantic_application") == last


async def test_projection_discards_the_children_of_a_discarded_model(
    env: dict[str, str],
    catalog_view: FakeCatalogView,
) -> None:
    """Discarding the model removes every row it owned."""
    model_id, relationship_id, _ = await write_model(env, catalog_view)
    async with ModelApplication(catalog_view=catalog_view, env=env) as app:
        await app.discard_model(model_id)
        last = await app.recorder.max_notification_id()
    assert last is not None

    async with run_semantic_projection(env) as runner:
        await runner.wait(last, timeout=5.0)
        view: Any = runner.view

        assert await view.get_model(model_id) is None
        assert await view.list_entities(model_id) == []
        assert await view.get_relationship(relationship_id) is None
        assert await view.list_diagrams(model_id) == []


async def test_rebuilding_the_view_replays_the_whole_event_stream(
    env: dict[str, str],
    catalog_view: FakeCatalogView,
    events_url: str,
) -> None:
    """Dropping the read model and replaying restores the same state."""
    model_id, relationship_id, last = await write_model(env, catalog_view)
    async with run_semantic_projection(env) as runner:
        await runner.wait(last, timeout=5.0)
        before: Any = runner.view
        expected = (
            [entity.name for entity in await before.list_entities(model_id)],
            await before.get_relationship(relationship_id),
            [
                (row.entity_name, row.x, row.y)
                for row in await before.list_nodes(model_id, ALL_DIAGRAM)
            ],
        )

    await _reset_read_model(events_url)

    async with run_semantic_projection(env) as runner:
        await runner.wait(last, timeout=5.0)
        rebuilt: Any = runner.view
        assert (
            [entity.name for entity in await rebuilt.list_entities(model_id)],
            await rebuilt.get_relationship(relationship_id),
            [
                (row.entity_name, row.x, row.y)
                for row in await rebuilt.list_nodes(model_id, ALL_DIAGRAM)
            ],
        ) == expected


async def _reset_read_model(url: str) -> None:
    """Drops the read model, keeping the event store, and recreates its tables."""
    datastore = AsyncSQLAlchemyDatastore(url)
    try:
        view = SQLAlchemySemanticView(
            datastore=datastore,
            tracking_table=datastore.create_tracking_table("semantic_projection_tracking"),
        )
        async with datastore.transaction() as conn:
            await conn.run_sync(view_metadata.drop_all)
            await conn.execute(sa.text("DROP TABLE IF EXISTS semantic_projection_tracking"))
        await view.create_table()
    finally:
        await datastore.close()
