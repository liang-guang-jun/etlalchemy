"""Tests for the SemanticModel.graph convenience factory."""

from __future__ import annotations

from typing import cast

import pytest
from etlalchemy.semantic import (
    EquiJoin,
    Field,
    FieldRef,
    Materialization,
    QualifiedName,
    Rowset,
    SemanticEntity,
    SemanticModel,
    SemanticRegistry,
    SemanticRelationship,
    String,
    edges_for_selection,
    highest_priority_edges,
)

from semantic.builders import entity, relationship


def _registry(
    entities: tuple[SemanticEntity, ...],
    relationships: tuple[SemanticRelationship, ...],
    *,
    names: tuple[str, ...] | None = None,
) -> SemanticRegistry:
    """Build a registry, optionally registering entities under other names."""
    registry = SemanticRegistry()
    keys = names or tuple(item.alias for item in entities)
    registry.entities.update(
        {key: item for key, item in zip(keys, entities, strict=True)}
    )
    registry.relationships.extend(relationships)
    return registry


def test_graph_defaults_to_the_full_edge_set() -> None:
    """Without arguments every registry relationship is analysed."""
    a, b = entity("a"), entity("b")
    registry = _registry(
        (a, b),
        (relationship("ab", a, b), relationship("ba", b, a)),
    )

    model = SemanticModel(name="m", registry=registry)

    assert model.graph().has_cycle() is True


def test_graph_accepts_a_highest_priority_selection() -> None:
    """A highest-priority selection is analysed instead of the full set."""
    a, b = entity("a"), entity("b")
    registry = _registry(
        (a, b),
        (
            relationship("ab_lo", a, b, priority=1),
            relationship("ab_hi", a, b, priority=5),
            relationship("ba", b, a, priority=5),
        ),
    )

    model = SemanticModel(name="m", registry=registry)
    cycles = model.graph(highest_priority_edges(model.registry)).find_cycles()

    assert [item.name for item in cycles[0].relationships] == ["ab_hi", "ba"]


def test_graph_accepts_an_explicit_selection() -> None:
    """An explicit per-pair selection is analysed instead of the full set."""
    a, b = entity("a"), entity("b")
    registry = _registry(
        (a, b),
        (
            relationship("ab_lo", a, b, priority=1),
            relationship("ab_hi", a, b, priority=5),
            relationship("ba", b, a, priority=5),
        ),
    )

    model = SemanticModel(name="m", registry=registry)
    selection = edges_for_selection(model.registry, {(a.id, b.id): 1})
    cycles = model.graph(selection).find_cycles()

    assert [item.name for item in cycles[0].relationships] == ["ab_lo", "ba"]


def test_graph_labels_use_entity_aliases() -> None:
    """Entity aliases label the nodes; registry keys only mark them known."""
    a, b = entity("a_alias"), entity("b_alias")
    registry = _registry(
        (a, b),
        (relationship("ab", a, b),),
        names=("a", "b"),
    )

    model = SemanticModel(name="m", registry=registry)

    assert model.graph().nodes == ("a_alias", "b_alias")


def test_graph_marks_entities_missing_from_the_registry() -> None:
    """Unregistered entities keep the '?' prefix on their alias."""
    known_entity, stranger = entity("a"), entity("stranger")
    registry = _registry((known_entity,), (relationship("ab", known_entity, stranger),))

    model = SemanticModel(name="m", registry=registry)

    assert model.graph().nodes == ("?stranger", "a")


def test_graph_returns_a_new_service_on_every_call() -> None:
    """The service is built per call and never cached on the model."""
    a, b = entity("a"), entity("b")
    registry = _registry((a, b), (relationship("ab", a, b),))
    model = SemanticModel(name="m", registry=registry)

    assert model.graph() is not model.graph()


def _rowset(name: str, *columns: str, schema: str | None = None) -> Rowset:
    """Build a rowset of string columns, optionally schema-qualified."""
    return Rowset(
        name=QualifiedName(name, schema=schema),
        kind=Materialization.TABLE,
        fields={column: Field(column, String()) for column in columns},
    )


def test_register_entity_registers_and_returns_the_entity() -> None:
    """``register_entity`` stores the rowset under the name and returns it."""
    model = SemanticModel(name="crm")
    orders_rowset = _rowset("orders", "id", schema="sales")

    orders = model.register_entity("orders", orders_rowset)

    assert orders.alias == "orders"
    assert orders.relation is orders_rowset
    assert model.registry.entities["orders"] is orders


def test_register_entity_rejects_a_duplicate_name() -> None:
    """A name is registered once."""
    model = SemanticModel(name="crm")
    model.register_entity("orders", _rowset("orders", "id"))

    with pytest.raises(ValueError, match="already registered"):
        model.register_entity("orders", _rowset("orders", "id"))


def test_register_relationship_builds_the_join_from_field_names() -> None:
    """The join keys are named, so no FieldCollection has to be built."""
    model = SemanticModel(name="crm")
    orders = model.register_entity("orders", _rowset("orders", "id", "customer_id"))
    customers = model.register_entity("customers", _rowset("customers", "id"))

    relationship = model.register_relationship(
        "orders_customers",
        orders,
        ["customer_id"],
        customers,
        ["id"],
    )

    assert relationship.name == "orders_customers"
    assert relationship.source_alias() == "orders"
    assert relationship.target_alias() == "customers"
    condition = cast(EquiJoin, relationship.condition)
    assert condition.source.fields[0].name == "customer_id"
    assert condition.target.fields[0].name == "id"
    assert model.registry.relationships == [relationship]


def test_register_relationship_reports_an_unknown_field() -> None:
    """A field name that the rowset does not declare is a usage error."""
    model = SemanticModel(name="crm")
    orders = model.register_entity("orders", _rowset("orders", "id"))
    customers = model.register_entity("customers", _rowset("customers", "id"))

    with pytest.raises(ValueError, match="not in the rowset"):
        model.register_relationship(
            "orders_customers",
            orders,
            ["missing"],
            customers,
            ["id"],
        )


def test_register_relationship_rejects_a_duplicate_name() -> None:
    """A relationship name is registered once."""
    model = SemanticModel(name="crm")
    orders = model.register_entity("orders", _rowset("orders", "id"))
    model.register_relationship("orders_orders", orders, ["id"], orders, ["id"])

    with pytest.raises(ValueError, match="already registered"):
        model.register_relationship("orders_orders", orders, ["id"], orders, ["id"])


def test_register_measure_forwards_the_keyword_arguments() -> None:
    """``register_measure`` passes its keywords to Measure unchanged."""
    model = SemanticModel(name="crm")

    measure = model.register_measure(
        "revenue",
        field=FieldRef(entity="orders", name="total"),
        aggregation="sum",
    )

    assert measure.name == "revenue"
    assert measure.aggregation == "sum"
    assert model.registry.measures["revenue"] is measure


def test_register_measure_rejects_a_duplicate_name() -> None:
    """A measure name is registered once."""
    model = SemanticModel(name="crm")
    field = FieldRef(entity="orders", name="total")
    model.register_measure("revenue", field=field)

    with pytest.raises(ValueError, match="already registered"):
        model.register_measure("revenue", field=field)
