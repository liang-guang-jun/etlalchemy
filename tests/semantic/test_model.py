"""Tests for the SemanticModel.graph convenience factory."""

from __future__ import annotations

from etlalchemy.semantic import (
    SemanticEntity,
    SemanticModel,
    SemanticRegistry,
    SemanticRelationship,
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
