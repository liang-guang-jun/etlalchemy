"""Tests for the diagram a semantic model draws of itself."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import FrozenInstanceError

import pytest
from etlalchemy.diagram import Diagram, DiagramNode
from etlalchemy.semantic import (
    Cardinality,
    FilterDirection,
    Integer,
    SemanticEntity,
    SemanticModel,
    SemanticRegistry,
    SemanticRelationship,
)


def node_named(diagram: Diagram, name: str) -> DiagramNode:
    return next(node for node in diagram.nodes if node.name == name)


def test_diagram_draws_every_entity_when_none_are_named(
    make_model: Callable[[], SemanticModel],
) -> None:
    diagram = make_model().diagram()

    assert isinstance(diagram, Diagram)
    assert [node.name for node in diagram.nodes] == [
        "Customer",
        "Order",
        "Payment",
    ]
    assert [edge.name for edge in diagram.edges] == [
        "customer_orders",
        "order_payments",
    ]


def test_diagram_draws_only_the_entities_it_is_given(
    make_model: Callable[[], SemanticModel],
) -> None:
    diagram = make_model().diagram("Order", "Payment")

    assert [node.name for node in diagram.nodes] == ["Order", "Payment"]


def test_diagram_resolves_entities_by_alias_by_name_and_by_id(
    make_model: Callable[[], SemanticModel],
    entity_id: Callable[[SemanticModel, str], str],
) -> None:
    model = make_model()
    diagram = model.diagram(entity_id(model, "Customer"), "customer", "Payment")

    assert [node.name for node in diagram.nodes] == ["Customer", "Payment"]


def test_diagram_keeps_the_order_the_entities_were_asked_for(
    make_model: Callable[[], SemanticModel],
) -> None:
    diagram = make_model().diagram("Payment", "Customer")

    assert [node.name for node in diagram.nodes] == ["Payment", "Customer"]


def test_diagram_draws_an_entity_named_twice_once(
    make_model: Callable[[], SemanticModel],
) -> None:
    diagram = make_model().diagram("Customer", "customer")

    assert [node.name for node in diagram.nodes] == ["Customer"]


def test_diagram_rejects_an_entity_it_cannot_find(
    make_model: Callable[[], SemanticModel],
) -> None:
    with pytest.raises(KeyError, match="Unknown entity reference"):
        make_model().diagram("Ghost")


def test_diagram_keeps_only_relationships_whose_ends_it_draws(
    make_model: Callable[[], SemanticModel],
) -> None:
    diagram = make_model().diagram("Order", "Payment")

    assert [edge.name for edge in diagram.edges] == ["order_payments"]


def test_diagram_draws_no_relationship_when_one_end_is_missing(
    make_model: Callable[[], SemanticModel],
) -> None:
    diagram = make_model().diagram("Customer", "Payment")

    assert diagram.edges == ()


def test_diagram_edge_carries_its_ends_columns_and_marks(
    make_model: Callable[[], SemanticModel],
    entity_id: Callable[[SemanticModel, str], str],
) -> None:
    model = make_model()
    edge = model.diagram("Customer", "Order").edges[0]

    assert edge.source_entity_id == entity_id(model, "Customer")
    assert edge.target_entity_id == entity_id(model, "Order")
    assert edge.source_columns == ("id",)
    assert edge.target_columns == ("customer_id",)
    assert edge.cardinality is Cardinality.ONE_TO_MANY
    assert edge.direction is FilterDirection.SINGLE


def test_diagram_marks_the_columns_a_drawn_relationship_joins(
    make_model: Callable[[], SemanticModel],
) -> None:
    diagram = make_model().diagram("Customer", "Order")

    assert [column.name for column in node_named(diagram, "Customer").columns] == [
        "id",
        "name",
    ]
    assert [
        column.name
        for column in node_named(diagram, "Order").columns
        if column.is_joined
    ] == ["customer_id"]
    assert [
        column.name
        for column in node_named(diagram, "Customer").columns
        if column.is_joined
    ] == ["id"]


def test_diagram_node_carries_primary_keys_and_types(
    make_model: Callable[[], SemanticModel],
) -> None:
    diagram = make_model().diagram("Order")
    order = node_named(diagram, "Order")

    assert order.columns[0].is_primary_key
    assert order.columns[0].data_type == "int"
    assert order.columns[2].data_type == "decimal(10,2)"
    assert not order.columns[1].is_primary_key


def test_diagram_node_carries_the_table_it_stands_for(
    make_model: Callable[[], SemanticModel],
) -> None:
    diagram = make_model().diagram("Order")

    assert node_named(diagram, "Order").table == "public.order"


def test_diagram_is_as_long_as_the_boxes_it_draws(
    make_model: Callable[[], SemanticModel],
) -> None:
    diagram = make_model().diagram("Order", "Payment")

    assert len(diagram) == 2


def test_diagram_rejects_a_box_it_does_not_draw(
    make_model: Callable[[], SemanticModel],
    entity_id: Callable[[SemanticModel, str], str],
) -> None:
    model = make_model()
    diagram = model.diagram("Order")

    with pytest.raises(KeyError, match="Diagram draws no entity"):
        diagram.node_for(entity_id(model, "Customer"))


def test_diagram_is_immutable(make_model: Callable[[], SemanticModel]) -> None:
    diagram = make_model().diagram()

    with pytest.raises(FrozenInstanceError):
        setattr(diagram, "nodes", ())


def test_an_empty_model_draws_an_empty_diagram() -> None:
    diagram = SemanticModel(name="Empty").diagram()

    assert diagram.nodes == ()
    assert diagram.edges == ()


def test_a_query_rowset_draws_no_table_name(
    query_entity: Callable[..., SemanticEntity],
) -> None:
    customer = query_entity("Customer", [("id", Integer())])
    model = SemanticModel(
        name="Sales",
        registry=SemanticRegistry(entities={"Customer": customer}),
    )

    assert model.diagram("Customer").nodes[0].table is None


def test_diagram_draws_one_way_and_two_way_relationships_differently(
    make_entity: Callable[..., SemanticEntity],
    relationship: Callable[..., SemanticRelationship],
) -> None:
    customer = make_entity("Customer", [("id", Integer())])
    order = make_entity("Order", [("customer_id", Integer())])
    model = SemanticModel(
        name="Sales",
        registry=SemanticRegistry(
            entities={"Customer": customer, "Order": order},
            relationships=[
                relationship(
                    "customer_orders",
                    customer,
                    "id",
                    order,
                    "customer_id",
                    cardinality=Cardinality.ONE_TO_ONE,
                    filter_direction=FilterDirection.BOTH,
                )
            ],
        ),
    )

    diagram = model.diagram()

    assert diagram.edges[0].cardinality is Cardinality.ONE_TO_ONE
    assert diagram.edges[0].direction is FilterDirection.BOTH


def test_edge_carries_the_priority_of_its_relationship(
    make_model: Callable[[], SemanticModel],
) -> None:
    diagram = make_model().diagram()
    edges = {edge.name: edge for edge in diagram.edges}

    assert edges["customer_orders"].priority == 0
    assert edges["order_payments"].priority == 2
