"""Tests for GraphService cycle detection and structural validation."""

from __future__ import annotations

from uuid import UUID, uuid5

import pytest
from etlalchemy.core import (
    Cardinality,
    Cycle,
    CycleKind,
    Field,
    FieldCollection,
    GraphService,
    Materialization,
    RelationshipCycleError,
    Rowset,
    SemanticEntity,
    SemanticRegistry,
    SemanticRelationship,
    String,
)

NAMESPACE = UUID("00000000-0000-0000-0000-000000000000")


def _entity(name: str) -> SemanticEntity:
    """Build a single-column entity named after its rowset."""
    fields = {"id": Field(name="id", data_type=String())}
    rowset = Rowset(name=name, kind=Materialization.TABLE, fields=fields)
    return SemanticEntity(id=uuid5(NAMESPACE, name), alias=name, relation=rowset)


def _registry(*names: str) -> tuple[SemanticRegistry, dict[str, SemanticEntity]]:
    """Build a registry plus a name-to-entity lookup."""
    registry = SemanticRegistry()
    entities = {name: _entity(name) for name in names}
    registry.entities.update(entities)
    return registry, entities


def _edge(
    registry: SemanticRegistry,
    name: str,
    source: SemanticEntity,
    target: SemanticEntity,
    cardinality: Cardinality = Cardinality.ONE_TO_MANY,
) -> SemanticRelationship:
    """Append a single-column relationship to the registry and return it."""
    relationship = SemanticRelationship(
        name=name,
        source=FieldCollection(source, (source.relation.fields["id"],)),
        target=FieldCollection(target, (target.relation.fields["id"],)),
        cardinality=cardinality,
    )
    registry.relationships.append(relationship)
    return relationship


def test_acyclic_chain_has_no_cycles() -> None:
    """A plain DAG reports no cycles and validates cleanly."""
    registry, entities = _registry("a", "b", "c")
    _edge(registry, "ab", entities["a"], entities["b"])
    _edge(registry, "bc", entities["b"], entities["c"])

    service = GraphService(registry)

    assert service.find_cycles() == ()
    assert service.has_cycle() is False
    assert service.validate() == ()
    service.ensure_acyclic()


def test_self_reference_is_a_cycle() -> None:
    """An entity referencing itself is a self-reference cycle."""
    registry, entities = _registry("a")
    _edge(registry, "self", entities["a"], entities["a"])

    cycles = GraphService(registry).find_cycles()

    assert len(cycles) == 1
    assert cycles[0].entities == ("a",)
    assert cycles[0].kind is CycleKind.SELF_REFERENCE
    assert str(cycles[0]) == "a -> a (SELF_REFERENCE)"


def test_two_entity_cycle_reported_once() -> None:
    """A -> B -> A is reported once, anchored at the smallest node."""
    registry, entities = _registry("a", "b")
    _edge(registry, "ab", entities["a"], entities["b"])
    _edge(registry, "ba", entities["b"], entities["a"])

    cycles = GraphService(registry).find_cycles()

    assert [cycle.entities for cycle in cycles] == [("a", "b")]
    assert [rel.name for rel in cycles[0].relationships] == ["ab", "ba"]


def test_three_entity_cycle() -> None:
    """Longer cycles keep their traversal order."""
    registry, entities = _registry("a", "b", "c")
    _edge(registry, "ab", entities["a"], entities["b"])
    _edge(registry, "bc", entities["b"], entities["c"])
    _edge(registry, "ca", entities["c"], entities["a"])

    cycles = GraphService(registry).find_cycles()

    assert [cycle.entities for cycle in cycles] == [("a", "b", "c")]


def test_cycle_kind_one_to_one() -> None:
    """A ring of one-to-one edges is classified as ONE_TO_ONE."""
    registry, entities = _registry("a", "b")
    _edge(registry, "ab", entities["a"], entities["b"], Cardinality.ONE_TO_ONE)
    _edge(registry, "ba", entities["b"], entities["a"], Cardinality.ONE_TO_ONE)

    assert GraphService(registry).find_cycles()[0].kind is CycleKind.ONE_TO_ONE


def test_cycle_kind_many_to_many() -> None:
    """Any many-to-many edge dominates the classification."""
    registry, entities = _registry("a", "b")
    _edge(registry, "ab", entities["a"], entities["b"], Cardinality.MANY_TO_MANY)
    _edge(registry, "ba", entities["b"], entities["a"], Cardinality.ONE_TO_MANY)

    assert GraphService(registry).find_cycles()[0].kind is CycleKind.MANY_TO_MANY


def test_cycle_kind_mixed() -> None:
    """One-to-many edges mixed with one-to-one edges are MIXED."""
    registry, entities = _registry("a", "b", "c")
    _edge(registry, "ab", entities["a"], entities["b"], Cardinality.ONE_TO_MANY)
    _edge(registry, "bc", entities["b"], entities["c"], Cardinality.ONE_TO_ONE)
    _edge(registry, "ca", entities["c"], entities["a"], Cardinality.ONE_TO_MANY)

    assert GraphService(registry).find_cycles()[0].kind is CycleKind.MIXED


def test_parallel_edges_are_not_a_cycle() -> None:
    """Two relationships between the same pair do not form a cycle."""
    registry, entities = _registry("a", "b")
    _edge(registry, "ab_1", entities["a"], entities["b"])
    _edge(registry, "ab_2", entities["a"], entities["b"])

    service = GraphService(registry)

    assert service.find_cycles() == ()
    assert service.has_cycle() is False


def test_find_cycles_is_deterministic() -> None:
    """Registry insertion order does not change the reported cycles."""
    forward, forward_entities = _registry("a", "b", "c")
    _edge(forward, "ab", forward_entities["a"], forward_entities["b"])
    _edge(forward, "ba", forward_entities["b"], forward_entities["a"])
    _edge(forward, "bc", forward_entities["b"], forward_entities["c"])
    _edge(forward, "cb", forward_entities["c"], forward_entities["b"])

    reverse, reverse_entities = _registry("c", "b", "a")
    _edge(reverse, "cb", reverse_entities["c"], reverse_entities["b"])
    _edge(reverse, "bc", reverse_entities["b"], reverse_entities["c"])
    _edge(reverse, "ba", reverse_entities["b"], reverse_entities["a"])
    _edge(reverse, "ab", reverse_entities["a"], reverse_entities["b"])

    assert GraphService(forward).find_cycles() == GraphService(reverse).find_cycles()


def test_edges_are_exposed_in_sorted_order() -> None:
    """Nodes, edges and neighbours are deterministic and sorted."""
    registry, entities = _registry("a", "b")
    _edge(registry, "ab", entities["a"], entities["b"])

    service = GraphService(registry)

    assert service.nodes == ("a", "b")
    assert service.edges == (("a", "b", "ab"),)
    assert service.neighbors("a") == ("b",)
    assert service.neighbors("b") == ()


def test_multiple_cycles_in_one_graph() -> None:
    """Independent cycles and a self-loop are all reported, in sorted order."""
    registry, entities = _registry("a", "b", "c")
    _edge(registry, "ab", entities["a"], entities["b"])
    _edge(registry, "ba", entities["b"], entities["a"])
    _edge(registry, "bb", entities["b"], entities["b"])
    _edge(registry, "bc", entities["b"], entities["c"])
    _edge(registry, "cb", entities["c"], entities["b"])

    cycles = GraphService(registry).find_cycles()

    assert [(cycle.entities, cycle.kind) for cycle in cycles] == [
        (("a", "b"), CycleKind.MIXED),
        (("b",), CycleKind.SELF_REFERENCE),
        (("b", "c"), CycleKind.MIXED),
    ]


def test_validate_reports_unknown_entity() -> None:
    """Relationships pointing outside the registry are reported."""
    registry, entities = _registry("a")
    _edge(registry, "gone", entities["a"], _entity("ghost"))

    problems = GraphService(registry).validate()

    assert problems == ("Relationship 'gone' references unknown entity 'ghost'",)


def test_ensure_acyclic_raises_with_cycle_details() -> None:
    """ensure_acyclic raises a RelationshipCycleError naming the cycle."""
    registry, entities = _registry("a", "b")
    _edge(registry, "ab", entities["a"], entities["b"])
    _edge(registry, "ba", entities["b"], entities["a"])

    with pytest.raises(RelationshipCycleError, match=r"a -> b -> a"):
        GraphService(registry).ensure_acyclic()


def test_cycle_dataclass_is_hashable() -> None:
    """Cycles can be collected in sets and compared by value."""
    cycle = Cycle(
        entities=("a", "b"),
        relationships=(),
        kind=CycleKind.MIXED,
    )

    assert hash(cycle) == hash(
        Cycle(entities=("a", "b"), relationships=(), kind=CycleKind.MIXED)
    )
