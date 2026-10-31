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


def _crm_model() -> tuple[SemanticModel, SemanticEntity, SemanticEntity]:
    """Return a model holding an orders and a customers entity."""
    model = SemanticModel(name="crm")
    orders = model.register_entity("orders", _rowset("orders", "id", "customer_id"))
    customers = model.register_entity("customers", _rowset("customers", "id"))
    return model, orders, customers


def test_register_entity_registers_and_returns_the_entity() -> None:
    """``register_entity`` stores the rowset under the name and returns it."""
    model = SemanticModel(name="crm")
    orders_rowset = _rowset("orders", "id", schema="sales")

    orders = model.register_entity("orders", orders_rowset)

    assert orders.alias == "orders"
    assert orders.relation is orders_rowset
    assert model.registry.entities["orders"] is orders


def test_register_entity_is_idempotent() -> None:
    """Registering the same name twice returns the first entity."""
    model = SemanticModel(name="crm")

    first = model.register_entity("orders", _rowset("orders", "id"))
    second = model.register_entity("orders", _rowset("orders", "id"))

    assert first is second
    assert len(model.registry.entities) == 1


def test_getitem_returns_a_proxy_and_rejects_an_unknown_name() -> None:
    """Entities are reached by registry name, and unknown names raise."""
    model, orders, _ = _crm_model()

    assert model["orders"].entity is orders

    with pytest.raises(KeyError, match="not registered"):
        model["missing"]


def test_register_relationship_builds_the_join_from_sliced_entities() -> None:
    """The join keys travel with the operands, so they cannot disagree."""
    model, _, _ = _crm_model()

    relationship = model.register_relationship(
        "orders_customers",
        model["orders"][["customer_id"]],
        model["customers"]["id"],
    )

    assert relationship.name == "orders_customers"
    assert relationship.source_alias() == "orders"
    assert relationship.target_alias() == "customers"
    condition = cast(EquiJoin, relationship.condition)
    assert condition.source.fields[0].name == "customer_id"
    assert condition.target.fields[0].name == "id"
    assert model.registry.relationships == [relationship]


def test_register_relationship_rejects_a_bare_entity() -> None:
    """Join keys must be picked explicitly."""
    model, orders, customers = _crm_model()

    with pytest.raises(ValueError, match="requires the join keys to be picked"):
        model.register_relationship("orders_customers", orders, customers)


def test_register_relationship_requires_a_picked_field() -> None:
    """An unsliced proxy carries no join key."""
    model, _, _ = _crm_model()

    with pytest.raises(ValueError, match="no fields selected"):
        model.register_relationship(
            "orders_customers",
            model["orders"],
            model["customers"]["id"],
        )


def test_register_relationship_reports_an_unknown_field() -> None:
    """A picked field the rowset does not declare is a usage error."""
    model, _, _ = _crm_model()

    with pytest.raises(ValueError, match="not in the rowset"):
        model.register_relationship(
            "orders_customers",
            model["orders"][["missing"]],
            model["customers"]["id"],
        )


def test_register_relationship_is_idempotent() -> None:
    """Registering the same name twice returns the first relationship."""
    model, _, _ = _crm_model()

    first = model.register_relationship(
        "orders_customers",
        model["orders"]["id"],
        model["customers"]["id"],
    )
    second = model.register_relationship(
        "orders_customers",
        model["orders"]["id"],
        model["customers"]["id"],
    )

    assert first is second
    assert model.registry.relationships == [first]


def test_register_measure_forwards_the_arguments() -> None:
    """The registration mirrors the Measure constructor."""
    model = SemanticModel(name="crm")
    field = FieldRef(entity="orders", name="total")

    measure = model.register_measure("revenue", field=field, aggregation="sum")

    assert measure.name == "revenue"
    assert measure.aggregation == "sum"
    assert measure.field is field
    assert model.registry.measures["revenue"] is measure


def test_register_measure_is_idempotent() -> None:
    """Registering the same name twice returns the first measure."""
    model = SemanticModel(name="crm")
    field = FieldRef(entity="orders", name="total")

    first = model.register_measure("revenue", field=field)
    second = model.register_measure("revenue", field=field)

    assert first is second
    assert len(model.registry.measures) == 1
