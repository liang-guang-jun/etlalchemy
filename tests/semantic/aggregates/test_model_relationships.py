"""Tests for the relationship commands of the semantic model aggregate."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from uuid import uuid4

import pytest
from etlalchemy.semantic.aggregates.errors import (
    DiscardedError,
    DuplicateRelationshipError,
    InvalidRelationshipError,
    UnknownRelationshipError,
)
from etlalchemy.semantic.aggregates.model import Model

REFS = (("orders", "customer_id"),)
TO_REFS = (("customers", "id"),)


def make_model() -> Model:
    """Returns a model with two entities and its creation event collected."""
    model = Model("sales")
    model.add_entity("customers", uuid4())
    model.add_entity("orders", uuid4())
    model.collect_events()
    return model


def test_adding_a_relationship_records_its_refs_and_settings() -> None:
    """A relationship stores both sides, the cardinality and the filter direction."""
    model = make_model()
    relationship_id = uuid4()

    model.add_relationship(
        relationship_id,
        REFS,
        TO_REFS,
        cardinality="one_to_many",
        filter_direction="both",
        priority=3,
    )

    relationship = model.relationships[relationship_id]
    assert relationship.from_refs == REFS
    assert relationship.to_refs == TO_REFS
    assert relationship.cardinality == "one_to_many"
    assert relationship.filter_direction == "both"
    assert relationship.priority == 3
    event = model.collect_events()[-1]
    assert isinstance(event, Model.RelationshipAdded)
    assert event.relationship_id == relationship_id
    assert event.from_refs == REFS
    assert event.to_refs == TO_REFS


def test_relationship_events_normalise_plain_lists_into_tuples() -> None:
    """A decoded JSON payload arrives as lists and must replay as tuples."""
    model = make_model()
    relationship_id = uuid4()

    model.add_relationship(
        relationship_id,
        [["orders", "customer_id"]],  # type: ignore[arg-type]
        [["customers", "id"]],  # type: ignore[arg-type]
        cardinality="one_to_many",
        filter_direction="single",
    )

    event = model.collect_events()[-1]
    assert isinstance(event, Model.RelationshipAdded)
    assert event.from_refs == REFS
    assert event.to_refs == TO_REFS
    assert all(isinstance(ref, tuple) for ref in event.from_refs)


def test_relationship_events_cannot_be_mutated() -> None:
    """Relationship events are immutable."""
    model = make_model()
    model.add_relationship(
        uuid4(),
        REFS,
        TO_REFS,
        cardinality="one_to_many",
        filter_direction="single",
    )
    event = model.collect_events()[-1]

    with pytest.raises(FrozenInstanceError):
        event.priority = 9  # type: ignore[misc]


def test_a_duplicate_relationship_id_is_rejected() -> None:
    """Relationship ids are unique inside one model."""
    model = make_model()
    relationship_id = uuid4()
    model.add_relationship(
        relationship_id,
        REFS,
        TO_REFS,
        cardinality="one_to_many",
        filter_direction="single",
    )
    model.collect_events()

    with pytest.raises(DuplicateRelationshipError, match=str(relationship_id)):
        model.add_relationship(
            relationship_id,
            REFS,
            TO_REFS,
            cardinality="one_to_one",
            filter_direction="single",
        )

    assert model.collect_events() == []


@pytest.mark.parametrize(
    ("from_refs", "to_refs"),
    [
        ((), ()),
        ((("orders", "customer_id"), ("orders", "id")), (("customers", "id"),)),
        ((("orders", "customer_id"),), ()),
    ],
)
def test_refs_of_different_lengths_are_rejected(
    from_refs: tuple[tuple[str, str], ...],
    to_refs: tuple[tuple[str, str], ...],
) -> None:
    """Both sides pair up item by item, so their lengths must match."""
    model = make_model()

    with pytest.raises(InvalidRelationshipError):
        model.add_relationship(
            uuid4(),
            from_refs,
            to_refs,
            cardinality="one_to_many",
            filter_direction="single",
        )


def test_a_ref_to_an_unknown_entity_is_rejected() -> None:
    """A relationship may only reference entities of the same model."""
    model = make_model()

    with pytest.raises(InvalidRelationshipError, match="ghosts"):
        model.add_relationship(
            uuid4(),
            (("ghosts", "id"),),
            TO_REFS,
            cardinality="one_to_one",
            filter_direction="single",
        )


@pytest.mark.parametrize("field", ["", "  "])
def test_a_ref_without_a_field_name_is_rejected(field: str) -> None:
    """Every ref names a field, so a blank field is invalid."""
    model = make_model()

    with pytest.raises(InvalidRelationshipError):
        model.add_relationship(
            uuid4(),
            (("orders", field),),
            TO_REFS,
            cardinality="one_to_one",
            filter_direction="single",
        )


def test_changing_a_relationship_overrides_only_the_given_attributes() -> None:
    """A change keeps every attribute it does not name."""
    model = make_model()
    relationship_id = uuid4()
    model.add_relationship(
        relationship_id,
        REFS,
        TO_REFS,
        cardinality="one_to_many",
        filter_direction="single",
        priority=1,
    )
    model.collect_events()

    model.change_relationship(relationship_id, cardinality="many_to_many", priority=7)

    relationship = model.relationships[relationship_id]
    assert relationship.cardinality == "many_to_many"
    assert relationship.priority == 7
    assert relationship.from_refs == REFS
    assert relationship.filter_direction == "single"
    event = model.collect_events()[-1]
    assert isinstance(event, Model.RelationshipChanged)
    assert event.cardinality == "many_to_many"
    assert event.from_refs is None


def test_changing_a_relationship_without_arguments_is_rejected() -> None:
    """A change that names no attribute is a caller error."""
    model = make_model()
    relationship_id = uuid4()
    model.add_relationship(
        relationship_id,
        REFS,
        TO_REFS,
        cardinality="one_to_many",
        filter_direction="single",
    )
    model.collect_events()

    with pytest.raises(ValueError, match="requires"):
        model.change_relationship(relationship_id)

    assert model.collect_events() == []


def test_changing_only_one_side_to_a_different_length_is_rejected() -> None:
    """The paired sides stay the same length after a partial change."""
    model = make_model()
    relationship_id = uuid4()
    model.add_relationship(
        relationship_id,
        REFS,
        TO_REFS,
        cardinality="one_to_many",
        filter_direction="single",
    )
    model.collect_events()

    with pytest.raises(InvalidRelationshipError):
        model.change_relationship(relationship_id, from_refs=(("orders", "id"), ("orders", "x")))

    assert model.collect_events() == []


def test_changing_an_unknown_relationship_is_rejected() -> None:
    """An unknown relationship id raises UnknownRelationshipError."""
    model = make_model()
    missing = uuid4()

    with pytest.raises(UnknownRelationshipError, match=str(missing)):
        model.change_relationship(missing, priority=1)


def test_removing_a_relationship_records_the_id() -> None:
    """Removing a relationship drops it and records RelationshipRemoved."""
    model = make_model()
    relationship_id = uuid4()
    model.add_relationship(
        relationship_id,
        REFS,
        TO_REFS,
        cardinality="one_to_many",
        filter_direction="single",
    )
    model.collect_events()

    model.remove_relationship(relationship_id)

    assert model.relationships == {}
    event = model.collect_events()[-1]
    assert isinstance(event, Model.RelationshipRemoved)
    assert event.relationship_id == relationship_id


def test_removing_an_unknown_relationship_is_rejected() -> None:
    """Removing an unknown relationship id raises UnknownRelationshipError."""
    model = make_model()

    with pytest.raises(UnknownRelationshipError):
        model.remove_relationship(uuid4())


def test_a_discarded_model_rejects_relationship_commands() -> None:
    """Every relationship command is guarded by ``_ensure_not_discarded``."""
    model = make_model()
    relationship_id = uuid4()
    model.add_relationship(
        relationship_id,
        REFS,
        TO_REFS,
        cardinality="one_to_many",
        filter_direction="single",
    )
    model.discard()

    with pytest.raises(DiscardedError):
        model.add_relationship(
            uuid4(),
            REFS,
            TO_REFS,
            cardinality="one_to_many",
            filter_direction="single",
        )
    with pytest.raises(DiscardedError):
        model.change_relationship(relationship_id, priority=2)
    with pytest.raises(DiscardedError):
        model.remove_relationship(relationship_id)
