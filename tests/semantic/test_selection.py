"""Tests for the priority selection helpers."""

from __future__ import annotations

from uuid import UUID

import pytest
from etlalchemy.semantic import (
    GraphService,
    SemanticEntity,
    SemanticRegistry,
    SemanticRelationship,
    all_edges,
    edges_by_priority,
    edges_for_selection,
    highest_priority_edges,
    lowest_priority_edges,
)

from semantic.builders import entity, relationship


def _registry(
    entities: tuple[SemanticEntity, ...],
    relationships: tuple[SemanticRelationship, ...],
) -> SemanticRegistry:
    """Build a registry from entities and relationships."""
    registry = SemanticRegistry()
    registry.entities.update({item.alias: item for item in entities})
    registry.relationships.extend(relationships)
    return registry


def _model() -> tuple[SemanticRegistry, SemanticEntity, SemanticEntity, SemanticEntity]:
    """Build a model whose cycle only appears when priorities are mixed."""
    a, b, c = entity("a"), entity("b"), entity("c")
    registry = _registry(
        (a, b, c),
        (
            relationship("ab_lo", a, b, priority=1),
            relationship("ab_hi", a, b, priority=5),
            relationship("bc", b, c, priority=0),
            relationship("ca", c, a, priority=5),
        ),
    )
    return registry, a, b, c


def test_all_edges_returns_every_relationship() -> None:
    """all_edges ignores priority and keeps the whole edge set."""
    registry, *_ = _model()

    names = {item.name for item in all_edges(registry)}

    assert names == {"ab_lo", "ab_hi", "bc", "ca"}
    assert len(all_edges(registry)) == 4


def test_all_edges_detects_mixed_priority_cycle() -> None:
    """A cycle needs a mix of priorities, so only the full set reveals it."""
    registry, *_ = _model()

    assert GraphService(all_edges(registry)).has_cycle() is True
    for edges in edges_by_priority(registry).values():
        assert GraphService(edges).has_cycle() is False


def test_all_edges_cycle_implies_some_selection_is_cyclic() -> None:
    """A three-pair cycle spanning two priorities is reported by all_edges."""
    a, b, c = entity("a"), entity("b"), entity("c")
    registry = _registry(
        (a, b, c),
        (
            relationship("ab", a, b, priority=0),
            relationship("bc", b, c, priority=1),
            relationship("ca", c, a, priority=0),
        ),
    )

    edges = all_edges(registry)

    assert {item.name for item in edges} == {"ab", "bc", "ca"}
    assert GraphService(edges).has_cycle() is True
    for level in edges_by_priority(registry).values():
        assert GraphService(level).has_cycle() is False


def test_all_edges_is_acyclic_when_every_selection_is_acyclic() -> None:
    """A full edge set without a cycle proves no selection can be cyclic."""
    a, b, c = entity("a"), entity("b"), entity("c")
    registry = _registry(
        (a, b, c),
        (
            relationship("ab_lo", a, b, priority=1),
            relationship("ab_hi", a, b, priority=5),
            relationship("bc", b, c, priority=2),
        ),
    )

    assert GraphService(all_edges(registry)).has_cycle() is False


def test_highest_priority_edges_picks_max_per_pair() -> None:
    """Only the highest-priority edge of each pair is kept."""
    registry, *_ = _model()

    names = {item.name for item in highest_priority_edges(registry)}

    assert names == {"ab_hi", "bc", "ca"}


def test_lowest_priority_edges_picks_min_per_pair() -> None:
    """Only the lowest-priority edge of each pair is kept."""
    registry, *_ = _model()

    names = {item.name for item in lowest_priority_edges(registry)}

    assert names == {"ab_lo", "bc", "ca"}


def test_priority_ties_select_the_smallest_name_in_both_directions() -> None:
    """Equal priorities resolve to the same edge for highest and lowest."""
    a, b = entity("a"), entity("b")
    registry = _registry(
        (a, b),
        (
            relationship("b", a, b, priority=2),
            relationship("a", a, b, priority=2),
        ),
    )

    assert [item.name for item in highest_priority_edges(registry)] == ["a"]
    assert [item.name for item in lowest_priority_edges(registry)] == ["a"]


def test_edges_for_selection_follows_the_mapping() -> None:
    """Selected pairs use the requested priority; others fall back to highest."""
    registry, a, b, _ = _model()

    names = {item.name for item in edges_for_selection(registry, {(a.id, b.id): 1})}

    assert names == {"ab_lo", "bc", "ca"}


def test_edges_for_selection_defaults_to_highest_priority() -> None:
    """An empty selection equals the default (highest priority) selection."""
    registry, *_ = _model()

    assert edges_for_selection(registry, {}) == highest_priority_edges(registry)


def test_edges_for_selection_rejects_unknown_priority() -> None:
    """Selecting a priority a pair does not offer names the pair and priority."""
    registry, a, b, _ = _model()

    with pytest.raises(ValueError) as excinfo:
        edges_for_selection(registry, {(a.id, b.id): 99})

    message = str(excinfo.value)
    assert str(a.id) in message
    assert str(b.id) in message
    assert "99" in message


def test_edges_for_selection_falls_back_for_missing_pairs() -> None:
    """Pairs absent from the mapping keep their highest-priority edge."""
    registry, a, b, c = _model()

    chosen = {
        (item.source.entity.id, item.target.entity.id): item.name
        for item in edges_for_selection(registry, {(c.id, a.id): 5})
    }

    assert chosen[(a.id, b.id)] == "ab_hi"
    assert chosen[(c.id, a.id)] == "ca"


def test_edges_for_selection_falls_back_when_a_pair_maps_to_none() -> None:
    """A pair explicitly mapped to None keeps its highest-priority edge."""
    registry, a, b, _ = _model()
    selection: dict[tuple[UUID, UUID], int] = {(a.id, b.id): None}  # type: ignore[dict-item]

    names = {item.name for item in edges_for_selection(registry, selection)}

    assert names == {"ab_hi", "bc", "ca"}


def test_edges_by_priority_groups_each_level() -> None:
    """Relationships are grouped by their own priority value."""
    registry, *_ = _model()

    grouped = edges_by_priority(registry)

    assert list(grouped) == [0, 1, 5]
    assert all(isinstance(items, tuple) for items in grouped.values())
    assert [item.name for item in grouped[0]] == ["bc"]
    assert [item.name for item in grouped[1]] == ["ab_lo"]
    assert {item.name for item in grouped[5]} == {"ab_hi", "ca"}


def test_helpers_handle_an_empty_registry() -> None:
    """Every helper returns an empty result for a registry without edges."""
    registry = SemanticRegistry()

    assert all_edges(registry) == ()
    assert highest_priority_edges(registry) == ()
    assert lowest_priority_edges(registry) == ()
    assert edges_for_selection(registry, {}) == ()
    assert edges_by_priority(registry) == {}
