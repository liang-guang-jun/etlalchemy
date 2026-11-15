"""Tests for the diagram commands of the semantic model aggregate."""

from __future__ import annotations

from uuid import uuid4

import pytest

from etlalchemy.semantic.aggregates.errors import (
    DiscardedError,
    DuplicateDiagramError,
    InvalidDiagramError,
    UnknownDiagramError,
)
from etlalchemy.semantic.aggregates.model import Model
from etlalchemy.semantic.aggregates.types import ALL_DIAGRAM


def make_model() -> Model:
    """Returns a model with one entity and its creation event collected."""
    model = Model("sales")
    model.add_entity("orders", uuid4())
    model.collect_events()
    return model


def test_adding_a_diagram_records_its_order() -> None:
    """A new diagram is stored by name and records DiagramAdded."""
    model = make_model()

    model.add_diagram("detail", order=2)

    assert model.diagrams["detail"].order == 2
    assert model.diagrams["detail"].name == "detail"
    event = model.collect_events()[-1]
    assert isinstance(event, Model.DiagramAdded)
    assert (event.name, event.order) == ("detail", 2)


def test_a_new_diagram_starts_without_nodes() -> None:
    """Only the All diagram receives nodes automatically."""
    model = make_model()

    model.add_diagram("detail")

    assert model.diagrams["detail"].nodes == {}
    assert set(model.diagrams[ALL_DIAGRAM].nodes) == {"orders"}


def test_a_duplicate_diagram_name_is_rejected() -> None:
    """Diagram names are unique inside one model."""
    model = make_model()
    model.add_diagram("detail")
    model.collect_events()

    with pytest.raises(DuplicateDiagramError, match="detail"):
        model.add_diagram("detail")

    assert model.collect_events() == []


@pytest.mark.parametrize("name", ["", "   ", "a/b", ALL_DIAGRAM])
def test_an_invalid_diagram_name_is_rejected(name: str) -> None:
    """A diagram name may not be blank, contain a separator or be ``All``."""
    model = make_model()

    with pytest.raises(InvalidDiagramError):
        model.add_diagram(name)

    assert model.collect_events() == []


def test_renaming_a_diagram_keeps_its_nodes() -> None:
    """Renaming moves the diagram, with its nodes, under the new key."""
    model = make_model()
    model.add_diagram("detail")
    model.place_node("detail", "orders", 5.0, 6.0)
    model.collect_events()

    model.rename_diagram("detail", "review")

    assert "detail" not in model.diagrams
    assert model.diagrams["review"].name == "review"
    assert model.diagrams["review"].nodes["orders"].x == 5.0
    event = model.collect_events()[-1]
    assert isinstance(event, Model.DiagramRenamed)
    assert (event.old_name, event.new_name) == ("detail", "review")


def test_renaming_a_diagram_to_its_own_name_records_nothing() -> None:
    """Renaming to the current name is a no-op."""
    model = make_model()
    model.add_diagram("detail")
    model.collect_events()
    version = model.version

    model.rename_diagram("detail", "detail")

    assert model.version == version
    assert model.collect_events() == []


def test_the_all_diagram_cannot_be_renamed() -> None:
    """All keeps its name, whichever side of the rename it is on."""
    model = make_model()

    with pytest.raises(InvalidDiagramError):
        model.rename_diagram(ALL_DIAGRAM, "overview")
    with pytest.raises(InvalidDiagramError):
        model.add_diagram("overview")
        model.rename_diagram("overview", ALL_DIAGRAM)


def test_renaming_an_unknown_diagram_is_rejected() -> None:
    """An unknown diagram name raises UnknownDiagramError."""
    model = make_model()

    with pytest.raises(UnknownDiagramError, match="detail"):
        model.rename_diagram("detail", "review")


def test_changing_a_diagram_order_is_recorded() -> None:
    """The order is a plain display hint and is updatable on every diagram."""
    model = make_model()
    model.add_diagram("detail")
    model.collect_events()

    model.change_diagram_order("detail", 4)
    model.change_diagram_order(ALL_DIAGRAM, 9)

    assert model.diagrams["detail"].order == 4
    assert model.diagrams[ALL_DIAGRAM].order == 9
    event = model.collect_events()[-1]
    assert isinstance(event, Model.DiagramOrderChanged)
    assert (event.name, event.order) == (ALL_DIAGRAM, 9)


def test_changing_a_diagram_to_its_current_order_records_nothing() -> None:
    """Re-sending the same order is a no-op."""
    model = make_model()
    model.change_diagram_order(ALL_DIAGRAM, 0)
    model.collect_events()

    model.change_diagram_order(ALL_DIAGRAM, 0)

    assert model.collect_events() == []


def test_changing_the_order_of_an_unknown_diagram_is_rejected() -> None:
    """An unknown diagram name raises UnknownDiagramError."""
    model = make_model()

    with pytest.raises(UnknownDiagramError):
        model.change_diagram_order("detail", 1)


def test_removing_a_diagram_drops_its_nodes() -> None:
    """Removing a diagram removes the diagram and the nodes it owned."""
    model = make_model()
    model.add_diagram("detail")
    model.place_node("detail", "orders", 1.0, 1.0)
    model.collect_events()

    model.remove_diagram("detail")

    assert "detail" not in model.diagrams
    assert set(model.diagrams[ALL_DIAGRAM].nodes) == {"orders"}
    event = model.collect_events()[-1]
    assert isinstance(event, Model.DiagramRemoved)
    assert event.name == "detail"


def test_the_all_diagram_cannot_be_removed() -> None:
    """Every model keeps at least the All overview."""
    model = make_model()

    with pytest.raises(InvalidDiagramError):
        model.remove_diagram(ALL_DIAGRAM)


def test_removing_an_unknown_diagram_is_rejected() -> None:
    """An unknown diagram name raises UnknownDiagramError."""
    model = make_model()

    with pytest.raises(UnknownDiagramError):
        model.remove_diagram("detail")


def test_a_discarded_model_rejects_diagram_commands() -> None:
    """Every diagram command is guarded by ``_ensure_not_discarded``."""
    model = make_model()
    model.add_diagram("detail")
    model.discard()

    with pytest.raises(DiscardedError):
        model.add_diagram("review")
    with pytest.raises(DiscardedError):
        model.rename_diagram("detail", "review")
    with pytest.raises(DiscardedError):
        model.change_diagram_order("detail", 1)
    with pytest.raises(DiscardedError):
        model.remove_diagram("detail")
