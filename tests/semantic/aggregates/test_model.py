"""Tests for the semantic model aggregate: lifecycle, entities and naming."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, is_dataclass
from typing import Any
from uuid import uuid4

import pytest

from etlalchemy.semantic.aggregates.errors import (
    DiscardedError,
    DuplicateEntityError,
    EntityInUseError,
    InvalidEntityNameError,
    UnknownEntityError,
)
from etlalchemy.semantic.aggregates.model import Model
from etlalchemy.semantic.aggregates.types import ALL_DIAGRAM

EVENT_CLASSES = [
    Model.Started,
    Model.Changed,
    Model.Discarded,
    Model.EntityAdded,
    Model.EntityRenamed,
    Model.EntityTableChanged,
    Model.EntityRemoved,
    Model.RelationshipAdded,
    Model.RelationshipChanged,
    Model.RelationshipRemoved,
    Model.DiagramAdded,
    Model.DiagramRenamed,
    Model.DiagramOrderChanged,
    Model.DiagramRemoved,
    Model.NodePlaced,
    Model.NodeMoved,
    Model.NodeRemoved,
]


def replay(events: list[Any]) -> Model:
    """Rebuilds a model by applying the given events in order."""
    aggregate: Any = None
    for event in events:
        aggregate = event.mutate(aggregate)
    assert isinstance(aggregate, Model)
    return aggregate


def make_model() -> Model:
    """Returns a model with its creation event already collected."""
    model = Model("sales")
    model.collect_events()
    return model


def test_creating_a_model_records_a_started_event_and_owns_all() -> None:
    """Creating a model stores its attributes and seeds the All diagram."""
    model = Model("sales", "Sales model")

    assert model.name == "sales"
    assert model.description == "Sales model"
    assert model.entities == {}
    assert model.relationships == {}
    assert list(model.diagrams) == [ALL_DIAGRAM]
    assert model.diagrams[ALL_DIAGRAM].nodes == {}

    events = model.collect_events()
    assert len(events) == 1
    assert isinstance(events[0], Model.Started)
    assert events[0].name == "sales"
    assert events[0].originator_version == 1


def test_replaying_the_events_rebuilds_the_all_diagram() -> None:
    """The All diagram comes from the constructor, so replay restores it."""
    events = Model("sales").collect_events()

    model = replay(events)

    assert model.name == "sales"
    assert list(model.diagrams) == [ALL_DIAGRAM]


def test_event_classes_are_frozen_dataclasses() -> None:
    """Every model event is an explicitly declared frozen dataclass."""
    for event_class in EVENT_CLASSES:
        assert is_dataclass(event_class), event_class.__qualname__
        assert event_class.__dataclass_params__.frozen, event_class.__qualname__


def test_events_cannot_be_mutated_after_creation() -> None:
    """Model events are immutable."""
    event = Model("sales").collect_events()[0]

    with pytest.raises(FrozenInstanceError):
        event.name = "other"  # type: ignore[misc]


def test_changing_a_model_records_the_new_attributes() -> None:
    """A change overrides only the non-``None`` attributes."""
    model = make_model()

    model.change(name="revenue")

    assert model.name == "revenue"
    assert model.description == ""
    event = model.collect_events()[-1]
    assert isinstance(event, Model.Changed)
    assert event.name == "revenue"
    assert event.description is None


def test_changing_a_model_without_arguments_is_rejected() -> None:
    """A change that names no attribute is a caller error."""
    model = make_model()
    version = model.version

    with pytest.raises(ValueError, match="requires"):
        model.change()

    assert model.version == version
    assert model.collect_events() == []


def test_a_discarded_model_rejects_further_changes() -> None:
    """Every command after ``discard`` raises DiscardedError."""
    model = make_model()
    model.discard()
    model.collect_events()

    with pytest.raises(DiscardedError):
        model.discard()
    with pytest.raises(DiscardedError):
        model.change(name="other")
    with pytest.raises(DiscardedError):
        model.add_entity("orders", uuid4())


def test_added_entities_are_laid_out_diagonally_in_all() -> None:
    """Each new entity gets the next slot of the All overview."""
    model = make_model()
    first, second, third = uuid4(), uuid4(), uuid4()

    model.add_entity("customers", first)
    model.add_entity("orders", second)
    model.add_entity("lines", third)

    assert model.entities["orders"].table_id == second
    positions = {
        name: (node.x, node.y) for name, node in model.diagrams[ALL_DIAGRAM].nodes.items()
    }
    assert positions == {
        "customers": (0.0, 0.0),
        "orders": (40.0, 40.0),
        "lines": (80.0, 80.0),
    }
    event = model.collect_events()[-1]
    assert isinstance(event, Model.EntityAdded)
    assert event.entity_name == "lines"
    assert event.table_id == third
    assert (event.initial_x, event.initial_y) == (80.0, 80.0)


def test_a_duplicate_entity_name_is_rejected() -> None:
    """Entity names are unique inside one model."""
    model = make_model()
    model.add_entity("orders", uuid4())
    model.collect_events()
    version = model.version

    with pytest.raises(DuplicateEntityError, match="orders"):
        model.add_entity("orders", uuid4())

    assert model.version == version
    assert model.collect_events() == []


@pytest.mark.parametrize("name", ["", "   ", "sales/orders"])
def test_an_invalid_entity_name_is_rejected(name: str) -> None:
    """Entity names may not be blank or contain a path separator."""
    model = make_model()

    with pytest.raises(InvalidEntityNameError):
        model.add_entity(name, uuid4())

    assert model.collect_events() == []


def test_renaming_an_entity_updates_its_references_everywhere() -> None:
    """A rename rewrites the registry, every relationship ref and every node key."""
    model = make_model()
    table_id = uuid4()
    model.add_entity("customers", table_id)
    other = uuid4()
    model.add_entity("orders", other)
    model.add_relationship(
        uuid4(),
        (("orders", "customer_id"),),
        (("customers", "id"),),
        cardinality="one_to_many",
        filter_direction="single",
    )
    model.add_diagram("detail")
    model.place_node("detail", "customers", 10.0, 20.0)
    model.collect_events()

    model.rename_entity("customers", "clients")

    assert "customers" not in model.entities
    assert model.entities["clients"].table_id == table_id
    relationship = next(iter(model.relationships.values()))
    assert relationship.from_refs == (("orders", "customer_id"),)
    assert relationship.to_refs == (("clients", "id"),)
    assert "customers" not in model.diagrams[ALL_DIAGRAM].nodes
    assert model.diagrams[ALL_DIAGRAM].nodes["clients"].x == 0.0
    assert "customers" not in model.diagrams["detail"].nodes
    assert model.diagrams["detail"].nodes["clients"].x == 10.0
    event = model.collect_events()[-1]
    assert isinstance(event, Model.EntityRenamed)
    assert (event.old_name, event.new_name) == ("customers", "clients")


def test_renaming_an_entity_to_its_own_name_records_nothing() -> None:
    """Renaming to the current name is a no-op."""
    model = make_model()
    model.add_entity("customers", uuid4())
    model.collect_events()
    version = model.version

    model.rename_entity("customers", "customers")

    assert model.version == version
    assert model.collect_events() == []


def test_renaming_an_entity_onto_an_existing_name_is_rejected() -> None:
    """A rename may not collide with another entity."""
    model = make_model()
    model.add_entity("customers", uuid4())
    model.add_entity("orders", uuid4())
    model.collect_events()

    with pytest.raises(DuplicateEntityError, match="orders"):
        model.rename_entity("customers", "orders")

    assert model.collect_events() == []


@pytest.mark.parametrize("name", ["", "a/b"])
def test_renaming_an_entity_to_an_invalid_name_is_rejected(name: str) -> None:
    """The new name follows the same rules as a fresh one."""
    model = make_model()
    model.add_entity("customers", uuid4())

    with pytest.raises(InvalidEntityNameError):
        model.rename_entity("customers", name)


def test_renaming_an_unknown_entity_is_rejected() -> None:
    """Renaming a name the model does not know raises UnknownEntityError."""
    model = make_model()

    with pytest.raises(UnknownEntityError, match="customers"):
        model.rename_entity("customers", "clients")


def test_changing_the_table_of_an_entity_is_recorded() -> None:
    """An unreferenced entity may be pointed at another table."""
    model = make_model()
    model.add_entity("customers", uuid4())
    new_table = uuid4()
    model.collect_events()

    model.change_entity_table("customers", new_table)

    assert model.entities["customers"].table_id == new_table
    event = model.collect_events()[-1]
    assert isinstance(event, Model.EntityTableChanged)
    assert event.table_id == new_table


def test_changing_the_table_of_a_referenced_entity_is_rejected() -> None:
    """A referenced entity keeps its table, so no relationship loses its fields."""
    model = make_model()
    model.add_entity("customers", uuid4())
    model.add_entity("orders", uuid4())
    model.add_relationship(
        uuid4(),
        (("customers", "id"),),
        (("orders", "customer_id"),),
        cardinality="one_to_many",
        filter_direction="single",
    )
    model.collect_events()

    with pytest.raises(EntityInUseError, match="customers"):
        model.change_entity_table("customers", uuid4())

    assert model.collect_events() == []


def test_removing_an_entity_cascades_to_relationships_and_nodes() -> None:
    """Removing an entity drops every relationship and node that mentions it."""
    model = make_model()
    model.add_entity("customers", uuid4())
    model.add_entity("orders", uuid4())
    model.add_diagram("detail")
    model.place_node("detail", "customers", 1.0, 1.0)
    model.add_relationship(
        uuid4(),
        (("customers", "id"),),
        (("orders", "customer_id"),),
        cardinality="one_to_many",
        filter_direction="single",
    )
    model.collect_events()

    model.remove_entity("customers")

    assert "customers" not in model.entities
    assert model.relationships == {}
    assert "customers" not in model.diagrams[ALL_DIAGRAM].nodes
    assert model.diagrams["detail"].nodes == {}
    assert set(model.diagrams[ALL_DIAGRAM].nodes) == set(model.entities)
    event = model.collect_events()[-1]
    assert isinstance(event, Model.EntityRemoved)
    assert event.entity_name == "customers"


def test_removing_an_unknown_entity_is_rejected() -> None:
    """Removing a name the model does not know raises UnknownEntityError."""
    model = make_model()

    with pytest.raises(UnknownEntityError, match="customers"):
        model.remove_entity("customers")
