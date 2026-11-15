"""Tests for the node commands of the semantic model aggregate."""

from __future__ import annotations

from uuid import uuid4

import pytest

from etlalchemy.semantic.aggregates.errors import (
    DiscardedError,
    DuplicateNodeError,
    InvalidDiagramError,
    UnknownDiagramError,
    UnknownEntityError,
    UnknownNodeError,
)
from etlalchemy.semantic.aggregates.model import Model
from etlalchemy.semantic.aggregates.types import ALL_DIAGRAM


def make_model() -> Model:
    """Returns a model with two entities, a detail diagram, events collected."""
    model = Model("sales")
    model.add_entity("customers", uuid4())
    model.add_entity("orders", uuid4())
    model.add_diagram("detail")
    model.collect_events()
    return model


def test_placing_a_node_records_its_position() -> None:
    """A node is stored under the entity name with the given coordinates."""
    model = make_model()

    model.place_node("detail", "orders", 12.5, -3.0)

    node = model.diagrams["detail"].nodes["orders"]
    assert (node.entity, node.x, node.y) == ("orders", 12.5, -3.0)
    event = model.collect_events()[-1]
    assert isinstance(event, Model.NodePlaced)
    assert (event.diagram_name, event.entity_name) == ("detail", "orders")
    assert (event.x, event.y) == (12.5, -3.0)


def test_placing_the_same_node_twice_is_rejected() -> None:
    """One entity appears at most once per diagram."""
    model = make_model()
    model.place_node("detail", "orders", 0.0, 0.0)
    model.collect_events()

    with pytest.raises(DuplicateNodeError, match="orders"):
        model.place_node("detail", "orders", 1.0, 1.0)

    assert model.collect_events() == []


def test_the_all_diagram_rejects_manual_nodes() -> None:
    """All manages its nodes from the entity list."""
    model = make_model()

    with pytest.raises(InvalidDiagramError):
        model.place_node(ALL_DIAGRAM, "orders", 1.0, 1.0)
    with pytest.raises(InvalidDiagramError):
        model.remove_node(ALL_DIAGRAM, "orders")


def test_placing_a_node_on_an_unknown_diagram_is_rejected() -> None:
    """An unknown diagram name raises UnknownDiagramError."""
    model = make_model()

    with pytest.raises(UnknownDiagramError, match="review"):
        model.place_node("review", "orders", 0.0, 0.0)


def test_placing_a_node_for_an_unknown_entity_is_rejected() -> None:
    """Only entities of the same model can be placed."""
    model = make_model()

    with pytest.raises(UnknownEntityError, match="ghosts"):
        model.place_node("detail", "ghosts", 0.0, 0.0)


def test_moving_a_node_updates_its_position() -> None:
    """A move replaces the coordinates of an existing node."""
    model = make_model()
    model.place_node("detail", "orders", 0.0, 0.0)
    model.collect_events()

    model.move_node("detail", "orders", 40.0, 60.0)

    node = model.diagrams["detail"].nodes["orders"]
    assert (node.x, node.y) == (40.0, 60.0)
    event = model.collect_events()[-1]
    assert isinstance(event, Model.NodeMoved)
    assert (event.x, event.y) == (40.0, 60.0)


def test_the_all_diagram_allows_moving_its_nodes() -> None:
    """The overview layout is the user's, so its nodes can be moved."""
    model = make_model()

    model.move_node(ALL_DIAGRAM, "orders", 100.0, 200.0)

    assert model.diagrams[ALL_DIAGRAM].nodes["orders"].x == 100.0
    assert model.diagrams[ALL_DIAGRAM].nodes["orders"].y == 200.0


def test_moving_a_node_to_its_current_position_records_nothing() -> None:
    """Re-sending the same drag is a no-op."""
    model = make_model()
    model.place_node("detail", "orders", 40.0, 60.0)
    model.collect_events()
    version = model.version

    model.move_node("detail", "orders", 40.0, 60.0)

    assert model.version == version
    assert model.collect_events() == []


def test_moving_an_unknown_node_is_rejected() -> None:
    """A diagram without that node raises UnknownNodeError."""
    model = make_model()

    with pytest.raises(UnknownNodeError, match="orders"):
        model.move_node("detail", "orders", 1.0, 1.0)


def test_removing_a_node_records_the_removal() -> None:
    """Removing a node drops it from the diagram."""
    model = make_model()
    model.place_node("detail", "orders", 0.0, 0.0)
    model.collect_events()

    model.remove_node("detail", "orders")

    assert model.diagrams["detail"].nodes == {}
    event = model.collect_events()[-1]
    assert isinstance(event, Model.NodeRemoved)
    assert (event.diagram_name, event.entity_name) == ("detail", "orders")


def test_removing_an_unknown_node_is_rejected() -> None:
    """A diagram without that node raises UnknownNodeError."""
    model = make_model()

    with pytest.raises(UnknownNodeError):
        model.remove_node("detail", "orders")


def test_the_all_diagram_always_shows_every_entity() -> None:
    """Adding, renaming and removing entities keeps the overview in sync."""
    model = Model("sales")
    model.add_entity("customers", uuid4())
    assert set(model.diagrams[ALL_DIAGRAM].nodes) == set(model.entities)

    model.add_entity("orders", uuid4())
    assert set(model.diagrams[ALL_DIAGRAM].nodes) == set(model.entities)

    model.rename_entity("orders", "lines")
    assert set(model.diagrams[ALL_DIAGRAM].nodes) == set(model.entities)

    model.remove_entity("customers")
    assert set(model.diagrams[ALL_DIAGRAM].nodes) == set(model.entities)


def test_a_discarded_model_rejects_node_commands() -> None:
    """Every node command is guarded by ``_ensure_not_discarded``."""
    model = make_model()
    model.place_node("detail", "orders", 0.0, 0.0)
    model.discard()

    with pytest.raises(DiscardedError):
        model.place_node("detail", "customers", 0.0, 0.0)
    with pytest.raises(DiscardedError):
        model.move_node("detail", "orders", 1.0, 1.0)
    with pytest.raises(DiscardedError):
        model.remove_node("detail", "orders")
