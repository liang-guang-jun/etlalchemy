"""Tests for GraphService cycle detection over explicit relationship sets."""

from __future__ import annotations

from typing import Any, cast

import pytest
from etlalchemy.semantic import (
    Cardinality,
    Cycle,
    CycleKind,
    GraphService,
    RelationshipCycleError,
)
from etlalchemy.semantic.graph import _classify

from builders import entity, known, relationship


def test_acyclic_edge_set_has_no_cycle() -> None:
    """A DAG edge set reports no cycles and validates cleanly."""
    a, b, c = entity("a"), entity("b"), entity("c")
    edges = (relationship("ab", a, b), relationship("bc", b, c))

    service = GraphService(edges, known(a, b, c))

    assert service.nodes == ("a", "b", "c")
    assert service.has_cycle() is False
    assert service.find_cycles() == ()
    assert service.validate() == ()
    service.ensure_acyclic()


def test_cyclic_edge_set_is_detected() -> None:
    """has_cycle and find_cycles agree on a two-entity cycle."""
    a, b = entity("a"), entity("b")
    edges = (relationship("ab", a, b), relationship("ba", b, a))

    service = GraphService(edges, known(a, b))

    assert service.has_cycle() is True
    assert [cycle.entities for cycle in service.find_cycles()] == [("a", "b")]


def test_self_reference_is_a_cycle() -> None:
    """An entity relating to itself is a self-reference cycle."""
    a = entity("a")

    cycles = GraphService([relationship("self", a, a)], known(a)).find_cycles()

    assert len(cycles) == 1
    assert cycles[0].entities == ("a",)
    assert cycles[0].kind is CycleKind.SELF_REFERENCE


def test_three_entity_cycle_keeps_traversal_order() -> None:
    """Longer cycles keep the order of their edges."""
    a, b, c = entity("a"), entity("b"), entity("c")
    edges = (
        relationship("ab", a, b),
        relationship("bc", b, c),
        relationship("ca", c, a),
    )

    cycles = GraphService(edges, known(a, b, c)).find_cycles()

    assert [cycle.entities for cycle in cycles] == [("a", "b", "c")]


def test_cycle_kind_one_to_one() -> None:
    """A ring of one-to-one edges is classified as ONE_TO_ONE."""
    a, b = entity("a"), entity("b")
    edges = (
        relationship("ab", a, b, cardinality=Cardinality.ONE_TO_ONE),
        relationship("ba", b, a, cardinality=Cardinality.ONE_TO_ONE),
    )

    cycle = GraphService(edges, known(a, b)).find_cycles()[0]

    assert cycle.kind is CycleKind.ONE_TO_ONE


def test_cycle_kind_many_to_many() -> None:
    """Any many-to-many edge dominates the classification."""
    a, b = entity("a"), entity("b")
    edges = (
        relationship("ab", a, b, cardinality=Cardinality.MANY_TO_MANY),
        relationship("ba", b, a),
    )

    cycle = GraphService(edges, known(a, b)).find_cycles()[0]

    assert cycle.kind is CycleKind.MANY_TO_MANY


def test_cycle_kind_mixed() -> None:
    """One-to-many plus one-to-one edges are classified as MIXED."""
    a, b, c = entity("a"), entity("b"), entity("c")
    edges = (
        relationship("ab", a, b),
        relationship("bc", b, c, cardinality=Cardinality.ONE_TO_ONE),
        relationship("ca", c, a),
    )

    cycle = GraphService(edges, known(a, b, c)).find_cycles()[0]

    assert cycle.kind is CycleKind.MIXED


def test_parallel_edges_report_single_cycle() -> None:
    """Parallel relationships on the same node sequence yield one cycle."""
    a, b = entity("a"), entity("b")
    edges = (
        relationship("ab_hi", a, b, priority=5),
        relationship("ab_lo", a, b, priority=1),
        relationship("ba", b, a),
    )

    cycles = GraphService(edges, known(a, b)).find_cycles()

    assert [cycle.entities for cycle in cycles] == [("a", "b")]
    assert [item.name for item in cycles[0].relationships] == ["ab_hi", "ba"]


def test_unknown_entities_get_prefixed_label() -> None:
    """Entities missing from known_entities are labelled with a '?' prefix."""
    a, ghost = entity("a"), entity("ghost")

    service = GraphService([relationship("gone", a, ghost)], known(a))

    assert service.nodes == ("?ghost", "a")
    assert service.edges == (("a", "?ghost", "gone"),)


def test_entities_are_identified_by_alias() -> None:
    """Two entities sharing an alias collapse into one node."""
    listed = entity("orders")
    twin = entity("orders", id_text="orders-twin")

    service = GraphService([relationship("link", twin, listed)], known(listed))

    assert service.nodes == ("orders",)
    assert service.edges == (("orders", "orders", "link"),)


def test_validate_reports_unknown_entities() -> None:
    """Relationships reaching outside the known entities are reported."""
    a, ghost = entity("a"), entity("ghost")

    problems = GraphService([relationship("gone", a, ghost)], known(a)).validate()

    assert problems == ("Relationship 'gone' references unknown entity '?ghost'",)


def test_edges_and_neighbors_are_sorted() -> None:
    """Nodes, edges and neighbours are deterministic and sorted."""
    a, b = entity("a"), entity("b")

    service = GraphService([relationship("ab", a, b)], known(a, b))

    assert service.nodes == ("a", "b")
    assert service.edges == (("a", "b", "ab"),)
    assert service.neighbors("a") == ("b",)
    assert service.neighbors("b") == ()


def test_multiple_cycles_reported_in_deterministic_order() -> None:
    """Independent cycles and a self-loop are all reported, in sorted order."""
    a, b, c = entity("a"), entity("b"), entity("c")
    edges = (
        relationship("ab", a, b),
        relationship("ba", b, a),
        relationship("bb", b, b),
        relationship("bc", b, c),
        relationship("cb", c, b),
    )

    cycles = GraphService(edges, known(a, b, c)).find_cycles()

    assert [(cycle.entities, cycle.kind) for cycle in cycles] == [
        (("a", "b"), CycleKind.MIXED),
        (("b",), CycleKind.SELF_REFERENCE),
        (("b", "c"), CycleKind.MIXED),
    ]


def test_find_cycles_is_deterministic() -> None:
    """Input order does not change the reported cycles."""
    a, b, c = entity("a"), entity("b"), entity("c")
    forward = [
        relationship("ab", a, b),
        relationship("ba", b, a),
        relationship("bc", b, c),
        relationship("cb", c, b),
    ]
    labels = known(a, b, c)

    assert (
        GraphService(forward, labels).find_cycles()
        == GraphService(reversed(forward), labels).find_cycles()
    )


def test_ensure_acyclic_raises_with_cycle_details() -> None:
    """ensure_acyclic raises a RelationshipCycleError naming the cycle."""
    a, b = entity("a"), entity("b")
    edges = (relationship("ab", a, b), relationship("ba", b, a))

    with pytest.raises(RelationshipCycleError, match=r"a -> b -> a"):
        GraphService(edges, known(a, b)).ensure_acyclic()


def test_classify_rejects_single_non_self_edge() -> None:
    """A lone non-self edge is not a closed walk."""
    a, b = entity("a"), entity("b")

    with pytest.raises(ValueError, match="single non-self"):
        _classify([relationship("ab", a, b)])


def test_classify_accepts_single_self_edge() -> None:
    """A lone self edge is a closed walk."""
    a = entity("a")

    assert _classify([relationship("self", a, a)]) is CycleKind.SELF_REFERENCE


def test_cycle_str_format() -> None:
    """Cycles render as an arrow path followed by the kind."""
    cycle = Cycle(entities=("a", "b"), kind=CycleKind.ONE_TO_ONE)

    assert str(cycle) == "a -> b -> a (ONE_TO_ONE)"


def test_cycle_equality_ignores_relationships() -> None:
    """Equality and hashing only use the entities and the kind."""
    a, b = entity("a"), entity("b")
    with_edges = Cycle(("a", "b"), CycleKind.MIXED, (relationship("ab", a, b),))
    without_edges = Cycle(("a", "b"), CycleKind.MIXED)

    assert with_edges == without_edges
    assert hash(with_edges) == hash(without_edges)


def test_neighbors_rejects_unknown_node() -> None:
    """Unknown labels raise a KeyError that names the node."""
    a, b = entity("a"), entity("b")
    service = GraphService([relationship("ab", a, b)], known(a, b))

    with pytest.raises(KeyError) as excinfo:
        service.neighbors("missing")

    assert "Unknown node 'missing'" in str(excinfo.value)


def test_graph_index_adjacency_is_read_only() -> None:
    """The index adjacency mapping rejects mutation."""
    a, b = entity("a"), entity("b")
    service = GraphService([relationship("ab", a, b)], known(a, b))
    adjacency = cast("Any", service._index.adjacency)

    with pytest.raises(TypeError):
        adjacency["a"] = ()
