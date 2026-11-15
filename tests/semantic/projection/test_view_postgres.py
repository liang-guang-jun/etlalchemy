"""Integration tests for the PostgreSQL semantic read model.

These tests need a running PostgreSQL database. Point `TEST_DATABASE_URL` (or
`ETLALCHEMY_DSN`) at it, for example:

    docker compose -f docker/docker-compose.yml up -d --wait
    export TEST_DATABASE_URL=postgresql://etlalchemy:etlalchemy@localhost:55432/etlalchemy_test
"""

from __future__ import annotations

import itertools
import os
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
from eventsourcing.asyncio.sqlalchemy import AsyncSQLAlchemyDatastore
from eventsourcing.persistence import Tracking

from etlalchemy.semantic.aggregates.types import ALL_DIAGRAM
from etlalchemy.semantic.projection.sqlalchemy import SQLAlchemySemanticView
from tests.support import async_postgres_url

DSN = os.environ.get("TEST_DATABASE_URL") or os.environ.get("ETLALCHEMY_DSN")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DSN, reason="TEST_DATABASE_URL is not set"),
]

VIEW_TABLES = (
    "semantic_models",
    "semantic_entities",
    "semantic_relationships",
    "semantic_relationship_fields",
    "semantic_diagrams",
    "semantic_nodes",
    "semantic_projection_tracking",
)

UPSTREAM = "semantic-application"


async def drop_tables(datastore: AsyncSQLAlchemyDatastore) -> None:
    """Drops the semantic tables so every test starts from an empty read model."""
    async with datastore.engine.begin() as conn:
        for table in VIEW_TABLES:
            await conn.exec_driver_sql(f'DROP TABLE IF EXISTS "{table}" CASCADE')


@pytest.fixture
async def view() -> AsyncIterator[SQLAlchemySemanticView]:
    """Returns a PostgreSQL view whose tables were just created."""
    datastore = AsyncSQLAlchemyDatastore(async_postgres_url(DSN or ""))
    await drop_tables(datastore)
    semantic_view = SQLAlchemySemanticView(
        datastore=datastore,
        tracking_table=datastore.create_tracking_table("semantic_projection_tracking"),
    )
    await semantic_view.create_table()
    try:
        yield semantic_view
    finally:
        await datastore.close()


async def register_entity(
    view: SQLAlchemySemanticView,
    tracking: Tracking,
    model_id: UUID,
    name: str,
    *,
    x: float = 0.0,
    y: float = 0.0,
) -> UUID:
    """Registers one entity with its All node and returns the table ID."""
    table_id = uuid4()
    await view.register_entity(model_id, name, table_id, x, y, tracking)
    return table_id


async def test_the_view_stores_the_whole_model(
    view: SQLAlchemySemanticView,
) -> None:
    """Every part of the model round-trips through PostgreSQL."""
    counter = itertools.count(1)
    tracking = lambda: Tracking(UPSTREAM, next(counter))  # noqa: E731

    model_id = uuid4()
    await view.register_model(model_id, "sales", "Revenue model", tracking())
    customers = await register_entity(view, tracking(), model_id, "customers")
    orders = await register_entity(view, tracking(), model_id, "orders", x=40.0, y=40.0)
    relationship_id = uuid4()
    await view.register_relationship(
        relationship_id,
        model_id,
        [("customers", "id")],
        [("orders", "customer_id")],
        "one_to_many",
        "both",
        3,
        tracking(),
    )
    await view.register_diagram(model_id, "detail", 1, tracking())
    await view.place_node(model_id, "detail", "orders", 1.5, -2.5, tracking())

    model = await view.get_model(model_id)
    assert model is not None
    assert (model.name, model.description) == ("sales", "Revenue model")
    assert [(entity.name, entity.table_id) for entity in await view.list_entities(model_id)] == [
        ("customers", customers),
        ("orders", orders),
    ]
    relationship = await view.get_relationship(relationship_id)
    assert relationship is not None
    assert relationship.from_refs == [("customers", "id")]
    assert relationship.to_refs == [("orders", "customer_id")]
    assert (relationship.cardinality, relationship.filter_direction, relationship.priority) == (
        "one_to_many",
        "both",
        3,
    )
    assert [row.name for row in await view.list_diagrams(model_id)] == [ALL_DIAGRAM, "detail"]
    assert [
        (node.entity_name, node.x, node.y)
        for node in await view.list_nodes(model_id, "detail")
    ] == [("orders", 1.5, -2.5)]


async def test_renaming_an_entity_cascades_in_postgres(
    view: SQLAlchemySemanticView,
) -> None:
    """The rename rewrites the relationship fields and the node rows."""
    counter = itertools.count(1)
    tracking = lambda: Tracking(UPSTREAM, next(counter))  # noqa: E731

    model_id = uuid4()
    await view.register_model(model_id, "sales", "", tracking())
    await register_entity(view, tracking(), model_id, "customers")
    await register_entity(view, tracking(), model_id, "orders", x=40.0, y=40.0)
    relationship_id = uuid4()
    await view.register_relationship(
        relationship_id,
        model_id,
        [("customers", "id")],
        [("orders", "customer_id")],
        "one_to_many",
        "single",
        0,
        tracking(),
    )

    await view.rename_entity(model_id, "customers", "clients", tracking())

    relationship = await view.get_relationship(relationship_id)
    assert relationship is not None
    assert relationship.from_refs == [("clients", "id")]
    nodes = await view.list_nodes(model_id, ALL_DIAGRAM)
    assert [node.entity_name for node in nodes] == ["clients", "orders"]


async def test_removing_an_entity_cascades_in_postgres(
    view: SQLAlchemySemanticView,
) -> None:
    """The entity, its relationship and its nodes disappear together."""
    counter = itertools.count(1)
    tracking = lambda: Tracking(UPSTREAM, next(counter))  # noqa: E731

    model_id = uuid4()
    await view.register_model(model_id, "sales", "", tracking())
    await register_entity(view, tracking(), model_id, "customers")
    await register_entity(view, tracking(), model_id, "orders", x=40.0, y=40.0)
    relationship_id = uuid4()
    await view.register_relationship(
        relationship_id,
        model_id,
        [("customers", "id")],
        [("orders", "customer_id")],
        "one_to_one",
        "single",
        0,
        tracking(),
    )

    await view.remove_entity(model_id, "customers", tracking())

    assert [entity.name for entity in await view.list_entities(model_id)] == ["orders"]
    assert await view.get_relationship(relationship_id) is None
    assert [node.entity_name for node in await view.list_nodes(model_id, ALL_DIAGRAM)] == [
        "orders"
    ]


async def test_discarding_a_model_cascades_in_postgres(
    view: SQLAlchemySemanticView,
) -> None:
    """A discarded model hides itself and deletes everything it owned."""
    counter = itertools.count(1)
    tracking = lambda: Tracking(UPSTREAM, next(counter))  # noqa: E731

    model_id = uuid4()
    await view.register_model(model_id, "sales", "", tracking())
    await register_entity(view, tracking(), model_id, "orders", x=40.0, y=40.0)
    await view.register_diagram(model_id, "detail", 1, tracking())

    await view.discard_model(model_id, tracking())

    assert await view.get_model(model_id) is None
    assert await view.list_models() == []
    assert await view.list_entities(model_id) == []
    assert await view.list_diagrams(model_id) == []
    assert await view.list_nodes(model_id, ALL_DIAGRAM) == []
