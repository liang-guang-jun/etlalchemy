"""Tests for the SQLite semantic read model."""

from __future__ import annotations

import itertools
from collections.abc import Callable
from uuid import UUID, uuid4

import pytest
from eventsourcing.persistence import Tracking

from etlalchemy.semantic.aggregates.types import ALL_DIAGRAM
from etlalchemy.semantic.projection.sqlalchemy import SQLAlchemySemanticView

UPSTREAM = "semantic-application"

TrackingFactory = Callable[[], Tracking]


@pytest.fixture
def view(semantic_view: SQLAlchemySemanticView) -> SQLAlchemySemanticView:
    """Returns an empty view backed by a temporary database file."""
    return semantic_view


@pytest.fixture
def tracking() -> TrackingFactory:
    """Returns a factory of monotonically increasing tracking records."""
    counter = itertools.count(1)
    return lambda: Tracking(UPSTREAM, next(counter))


async def register_model(
    view: SQLAlchemySemanticView,
    tracking: Tracking,
    name: str = "sales",
    description: str = "",
) -> UUID:
    """Registers a model with its All diagram and returns its ID."""
    model_id = uuid4()
    await view.register_model(model_id, name, description, tracking)
    return model_id


async def register_entity(
    view: SQLAlchemySemanticView,
    tracking: Tracking,
    model_id: UUID,
    name: str,
    *,
    x: float = 0.0,
    y: float = 0.0,
) -> UUID:
    """Registers an entity with its All node, returning the table ID."""
    table_id = uuid4()
    await view.register_entity(model_id, name, table_id, x, y, tracking)
    return table_id


async def register_relationship(
    view: SQLAlchemySemanticView,
    tracking: Tracking,
    model_id: UUID,
    from_refs: list[tuple[str, str]],
    to_refs: list[tuple[str, str]],
) -> UUID:
    """Registers a relationship and returns its ID."""
    relationship_id = uuid4()
    await view.register_relationship(
        relationship_id,
        model_id,
        from_refs,
        to_refs,
        "one_to_many",
        "single",
        0,
        tracking,
    )
    return relationship_id


async def test_registering_a_model_upserts_the_row(
    view: SQLAlchemySemanticView,
    tracking: TrackingFactory,
) -> None:
    """Replaying the same registration keeps one row with the latest values."""
    model_id = uuid4()
    await view.register_model(model_id, "sales", "", tracking())
    await view.register_model(model_id, "sales", "Revenue model", tracking())

    row = await view.get_model(model_id)
    assert row is not None
    assert (row.model_id, row.name, row.description) == (model_id, "sales", "Revenue model")
    assert len(await view.list_models()) == 1


async def test_models_are_listed_by_name_and_skip_discarded_ones(
    view: SQLAlchemySemanticView,
    tracking: TrackingFactory,
) -> None:
    """Listing sorts by name and hides a discarded model."""
    second = await register_model(view, tracking(), "zebra")
    first = await register_model(view, tracking(), "analytics")
    dropped = await register_model(view, tracking(), "obsolete")
    await view.discard_model(dropped, tracking())

    rows = await view.list_models()

    assert [row.model_id for row in rows] == [first, second]
    assert await view.get_model(dropped) is None


async def test_changing_a_model_updates_only_the_given_attributes(
    view: SQLAlchemySemanticView,
    tracking: TrackingFactory,
) -> None:
    """A partial change keeps the attribute it does not name."""
    model_id = await register_model(view, tracking(), "sales", "Revenue model")

    await view.change_model(model_id, "revenue", None, tracking())

    row = await view.get_model(model_id)
    assert row is not None
    assert (row.name, row.description) == ("revenue", "Revenue model")


async def test_discarding_a_model_clears_every_row_it_owned(
    view: SQLAlchemySemanticView,
    tracking: TrackingFactory,
) -> None:
    """Discarding removes entities, relationships, diagrams and nodes."""
    model_id = await register_model(view, tracking())
    await register_entity(view, tracking(), model_id, "customers")
    await register_entity(view, tracking(), model_id, "orders", x=40.0, y=40.0)
    await register_relationship(
        view,
        tracking(),
        model_id,
        [("customers", "id")],
        [("orders", "customer_id")],
    )
    await view.register_diagram(model_id, "detail", 1, tracking())

    await view.discard_model(model_id, tracking())

    assert await view.list_entities(model_id) == []
    assert await view.list_relationships(model_id) == []
    assert await view.list_diagrams(model_id) == []
    assert await view.list_nodes(model_id, ALL_DIAGRAM) == []


async def test_entities_are_registered_read_and_listed_by_name(
    view: SQLAlchemySemanticView,
    tracking: TrackingFactory,
) -> None:
    """Entities are keyed by model and name and sorted when listed."""
    model_id = await register_model(view, tracking())
    customers_table = await register_entity(view, tracking(), model_id, "customers")
    await register_entity(view, tracking(), model_id, "orders")

    row = await view.get_entity(model_id, "customers")
    assert row is not None
    assert row.table_id == customers_table
    assert [entity.name for entity in await view.list_entities(model_id)] == [
        "customers",
        "orders",
    ]
    assert await view.get_entity(model_id, "ghosts") is None


async def test_changing_the_table_of_an_entity_keeps_its_rows(
    view: SQLAlchemySemanticView,
    tracking: TrackingFactory,
) -> None:
    """Only the table id changes."""
    model_id = await register_model(view, tracking())
    await register_entity(view, tracking(), model_id, "customers")
    new_table = uuid4()

    await view.change_entity_table(model_id, "customers", new_table, tracking())

    row = await view.get_entity(model_id, "customers")
    assert row is not None
    assert row.table_id == new_table


async def test_renaming_an_entity_rewrites_its_references_and_nodes(
    view: SQLAlchemySemanticView,
    tracking: TrackingFactory,
) -> None:
    """A rename cascades to the relationship fields and to every diagram."""
    model_id = await register_model(view, tracking())
    await register_entity(view, tracking(), model_id, "customers")
    await register_entity(view, tracking(), model_id, "orders", x=40.0, y=40.0)
    relationship_id = await register_relationship(
        view,
        tracking(),
        model_id,
        [("customers", "id")],
        [("orders", "customer_id")],
    )
    await view.register_diagram(model_id, "detail", 1, tracking())
    await view.place_node(model_id, "detail", "customers", 5.0, 6.0, tracking())

    await view.rename_entity(model_id, "customers", "clients", tracking())

    assert await view.get_entity(model_id, "customers") is None
    assert await view.get_entity(model_id, "clients") is not None
    relationship = await view.get_relationship(relationship_id)
    assert relationship is not None
    assert relationship.from_refs == [("clients", "id")]
    assert relationship.to_refs == [("orders", "customer_id")]
    all_nodes = await view.list_nodes(model_id, ALL_DIAGRAM)
    assert [node.entity_name for node in all_nodes] == ["clients", "orders"]
    detail_nodes = await view.list_nodes(model_id, "detail")
    assert [(node.entity_name, node.x) for node in detail_nodes] == [("clients", 5.0)]


async def test_removing_an_entity_cascades_in_the_view(
    view: SQLAlchemySemanticView,
    tracking: TrackingFactory,
) -> None:
    """Removing an entity drops the relationships and nodes that mention it."""
    model_id = await register_model(view, tracking())
    await register_entity(view, tracking(), model_id, "customers")
    await register_entity(view, tracking(), model_id, "orders", x=40.0, y=40.0)
    await register_relationship(
        view,
        tracking(),
        model_id,
        [("customers", "id")],
        [("orders", "customer_id")],
    )
    await view.register_diagram(model_id, "detail", 1, tracking())
    await view.place_node(model_id, "detail", "customers", 1.0, 1.0, tracking())

    await view.remove_entity(model_id, "customers", tracking())

    assert [entity.name for entity in await view.list_entities(model_id)] == ["orders"]
    assert await view.list_relationships(model_id) == []
    assert [node.entity_name for node in await view.list_nodes(model_id, ALL_DIAGRAM)] == [
        "orders"
    ]
    assert await view.list_nodes(model_id, "detail") == []


async def test_registering_a_relationship_stores_both_sides_in_order(
    view: SQLAlchemySemanticView,
    tracking: TrackingFactory,
) -> None:
    """The field rows keep their position and are rebuilt into paired refs."""
    model_id = await register_model(view, tracking())
    relationship_id = await register_relationship(
        view,
        tracking(),
        model_id,
        [("orders", "id"), ("orders", "customer_id")],
        [("customers", "id"), ("customers", "order_id")],
    )

    row = await view.get_relationship(relationship_id)

    assert row is not None
    assert row.from_refs == [("orders", "id"), ("orders", "customer_id")]
    assert row.to_refs == [("customers", "id"), ("customers", "order_id")]
    assert (row.cardinality, row.filter_direction, row.priority) == ("one_to_many", "single", 0)


async def test_replaying_a_relationship_registration_keeps_one_copy(
    view: SQLAlchemySemanticView,
    tracking: TrackingFactory,
) -> None:
    """The field rows are rewritten, so a replay does not duplicate them."""
    model_id = await register_model(view, tracking())
    relationship_id = uuid4()
    for _ in range(2):
        await view.register_relationship(
            relationship_id,
            model_id,
            [("orders", "customer_id")],
            [("customers", "id")],
            "one_to_one",
            "both",
            2,
            tracking(),
        )

    row = await view.get_relationship(relationship_id)
    assert row is not None
    assert row.from_refs == [("orders", "customer_id")]
    assert row.cardinality == "one_to_one"


async def test_changing_a_relationship_rewrites_only_the_given_side(
    view: SQLAlchemySemanticView,
    tracking: TrackingFactory,
) -> None:
    """Changing one side keeps the other side's refs intact."""
    model_id = await register_model(view, tracking())
    relationship_id = await register_relationship(
        view,
        tracking(),
        model_id,
        [("orders", "customer_id")],
        [("customers", "id")],
    )

    await view.change_relationship(
        relationship_id,
        [("orders", "buyer_id")],
        None,
        "many_to_many",
        None,
        5,
        tracking(),
    )

    row = await view.get_relationship(relationship_id)
    assert row is not None
    assert row.from_refs == [("orders", "buyer_id")]
    assert row.to_refs == [("customers", "id")]
    assert (row.cardinality, row.filter_direction, row.priority) == (
        "many_to_many",
        "single",
        5,
    )


async def test_relationships_are_listed_with_their_refs_ordered_by_priority(
    view: SQLAlchemySemanticView,
    tracking: TrackingFactory,
) -> None:
    """Listing returns every relationship of the model with both sides."""
    model_id = await register_model(view, tracking())
    low = await register_relationship(
        view,
        tracking(),
        model_id,
        [("orders", "customer_id")],
        [("customers", "id")],
    )
    await view.change_relationship(low, None, None, None, None, 9, tracking())
    high = await register_relationship(
        view,
        tracking(),
        model_id,
        [("lines", "order_id")],
        [("orders", "id")],
    )

    rows = await view.list_relationships(model_id)

    assert [row.relationship_id for row in rows] == [high, low]
    assert rows[0].from_refs == [("lines", "order_id")]


async def test_removing_a_relationship_removes_its_fields(
    view: SQLAlchemySemanticView,
    tracking: TrackingFactory,
) -> None:
    """The main row and the field rows go away together."""
    model_id = await register_model(view, tracking())
    relationship_id = await register_relationship(
        view,
        tracking(),
        model_id,
        [("orders", "customer_id")],
        [("customers", "id")],
    )

    await view.remove_relationship(relationship_id, tracking())

    assert await view.get_relationship(relationship_id) is None
    assert await view.list_relationships(model_id) == []


async def test_diagrams_are_listed_by_order_then_name(
    view: SQLAlchemySemanticView,
    tracking: TrackingFactory,
) -> None:
    """The All diagram sorts with the others by its order value."""
    model_id = await register_model(view, tracking())
    await view.register_diagram(model_id, "zeta", 2, tracking())
    await view.register_diagram(model_id, "alpha", 1, tracking())
    await view.change_diagram_order(model_id, ALL_DIAGRAM, 1, tracking())

    rows = await view.list_diagrams(model_id)

    assert [(row.name, row.order) for row in rows] == [
        (ALL_DIAGRAM, 1),
        ("alpha", 1),
        ("zeta", 2),
    ]
    assert await view.get_diagram(model_id, "alpha") is not None
    assert await view.get_diagram(model_id, "missing") is None


async def test_renaming_a_diagram_moves_its_nodes(
    view: SQLAlchemySemanticView,
    tracking: TrackingFactory,
) -> None:
    """Nodes follow the diagram to its new name."""
    model_id = await register_model(view, tracking())
    await register_entity(view, tracking(), model_id, "orders")
    await view.register_diagram(model_id, "detail", 1, tracking())
    await view.place_node(model_id, "detail", "orders", 3.0, 4.0, tracking())

    await view.rename_diagram(model_id, "detail", "review", tracking())

    assert await view.get_diagram(model_id, "detail") is None
    assert await view.get_diagram(model_id, "review") is not None
    nodes = await view.list_nodes(model_id, "review")
    assert [(node.diagram_name, node.x) for node in nodes] == [("review", 3.0)]


async def test_removing_a_diagram_removes_its_nodes(
    view: SQLAlchemySemanticView,
    tracking: TrackingFactory,
) -> None:
    """Only the nodes of the removed diagram disappear."""
    model_id = await register_model(view, tracking())
    await register_entity(view, tracking(), model_id, "orders")
    await view.register_diagram(model_id, "detail", 1, tracking())
    await view.place_node(model_id, "detail", "orders", 3.0, 4.0, tracking())

    await view.remove_diagram(model_id, "detail", tracking())

    assert [row.name for row in await view.list_diagrams(model_id)] == [ALL_DIAGRAM]
    assert await view.list_nodes(model_id, "detail") == []
    assert [node.entity_name for node in await view.list_nodes(model_id, ALL_DIAGRAM)] == [
        "orders"
    ]


async def test_nodes_are_upserted_and_moved(
    view: SQLAlchemySemanticView,
    tracking: TrackingFactory,
) -> None:
    """Placing twice keeps one node; a move updates its coordinates."""
    model_id = await register_model(view, tracking())
    await register_entity(view, tracking(), model_id, "orders")
    await view.place_node(model_id, ALL_DIAGRAM, "orders", 0.0, 0.0, tracking())

    await view.move_node(model_id, ALL_DIAGRAM, "orders", 12.5, -3.0, tracking())

    nodes = await view.list_nodes(model_id, ALL_DIAGRAM)
    assert [(node.entity_name, node.x, node.y) for node in nodes] == [("orders", 12.5, -3.0)]
    assert nodes[0].model_id == model_id


async def test_removing_a_node_keeps_the_entity(
    view: SQLAlchemySemanticView,
    tracking: TrackingFactory,
) -> None:
    """A node is removed without touching the entity or the other diagrams."""
    model_id = await register_model(view, tracking())
    await register_entity(view, tracking(), model_id, "orders")
    await view.register_diagram(model_id, "detail", 1, tracking())
    await view.place_node(model_id, "detail", "orders", 1.0, 1.0, tracking())

    await view.remove_node(model_id, "detail", "orders", tracking())

    assert await view.get_entity(model_id, "orders") is not None
    assert await view.list_nodes(model_id, "detail") == []
    assert len(await view.list_nodes(model_id, ALL_DIAGRAM)) == 1
