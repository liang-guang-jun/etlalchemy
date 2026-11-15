"""Tests for the term aggregate."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, is_dataclass, replace
from typing import Any
from uuid import uuid4

import pytest

from etlalchemy.vocabulary.aggregates.errors import (
    DiscardedError,
    DuplicateAliasError,
    InvalidAliasError,
    InvalidColorError,
    InvalidLinkError,
    InvalidPathError,
    InvalidTermNameError,
    InvalidTermStateError,
    UnknownAliasError,
    UnknownLinkError,
)
from etlalchemy.vocabulary.aggregates.term import Term
from etlalchemy.vocabulary.aggregates.types import TermLink, TermStatus

EVENT_CLASSES = [
    Term.Started,
    Term.ColorChanged,
    Term.DefinitionChanged,
    Term.AliasAdded,
    Term.AliasRemoved,
    Term.Approved,
    Term.Reopened,
    Term.Deprecated,
    Term.Reactivated,
    Term.Linked,
    Term.Unlinked,
    Term.Renamed,
    Term.Moved,
    Term.Repathed,
    Term.Discarded,
]


def replay(events: list[Any]) -> Term:
    """Rebuilds a term by applying the given events in order."""
    aggregate: Any = None
    for event in events:
        aggregate = event.mutate(aggregate)
    assert isinstance(aggregate, Term)
    return aggregate


def make_term(
    name: str = "invoice",
    definition: str = "A bill sent to a customer",
    aliases: tuple[str, ...] = ("bill",),
    parent_id: Any = None,
    path: str = "finance/invoice",
    color: str = "",
) -> Term:
    """Builds a term with the given tree position and colour."""
    return Term(uuid4(), name, definition, aliases, parent_id, path, color)


def approved_term() -> Term:
    """Returns an approved term that has collected its events."""
    term = make_term()
    term.approve("reviewer")
    term.collect_events()
    return term


def test_creating_a_term_records_its_tree_position() -> None:
    """Creating a term stores its domain, parent and path in Term.Started."""
    domain_id, parent_id = uuid4(), uuid4()

    term = Term(domain_id, "invoice", "A bill", ("bill",), parent_id, "finance/invoice")

    assert term.domain_id == domain_id
    assert term.parent_id == parent_id
    assert term.path == "finance/invoice"
    assert term.name == "invoice"
    assert term.aliases == {"bill": None}
    assert term.status is TermStatus.DRAFT
    assert term.links == {}

    events = term.collect_events()
    assert len(events) == 1
    assert isinstance(events[0], Term.Started)
    assert events[0].domain_id == domain_id
    assert events[0].parent_id == parent_id
    assert events[0].path == "finance/invoice"
    assert events[0].aliases == ("bill",)
    assert events[0].originator_version == 1


def test_a_top_level_term_defaults_its_path_to_its_name() -> None:
    """A term without a path is registered under its own name."""
    term = Term(uuid4(), "invoice", "A bill")

    assert term.parent_id is None
    assert term.path == "invoice"


@pytest.mark.parametrize("name", ["", "   ", "Revenue/ARR"])
def test_invalid_names_are_rejected(name: str) -> None:
    """A name must be one non-blank path segment."""
    with pytest.raises(InvalidTermNameError):
        Term(uuid4(), name, "A bill")


def test_a_path_must_end_with_the_term_name() -> None:
    """A path that belongs to another name is rejected on construction."""
    with pytest.raises(InvalidPathError, match="does not end with"):
        Term(uuid4(), "invoice", "A bill", path="sales/bill")


def test_a_started_event_with_a_bad_name_fails_on_replay() -> None:
    """Replay validates the name too, so corrupted events cannot build a term."""
    event = replace(make_term().collect_events()[0], name="A/B")

    with pytest.raises(InvalidTermNameError):
        event.mutate(None)


def test_event_classes_are_frozen_dataclasses() -> None:
    """Every term event is an explicitly declared frozen dataclass."""
    for event_class in EVENT_CLASSES:
        assert is_dataclass(event_class), event_class.__qualname__
        assert event_class.__dataclass_params__.frozen, event_class.__qualname__


def test_events_cannot_be_mutated_after_creation() -> None:
    """Term events are immutable."""
    event = make_term().collect_events()[0]

    with pytest.raises(FrozenInstanceError):
        event.name = "other"  # type: ignore[misc]


def test_draft_content_can_be_edited() -> None:
    """Definition and aliases are editable while the term is a draft."""
    term = make_term()
    term.collect_events()

    term.change_definition("A bill to a customer")
    term.add_alias("invoice document")
    term.remove_alias("bill")

    assert term.definition == "A bill to a customer"
    assert term.aliases == {"invoice document": None}


def test_duplicate_alias_is_rejected() -> None:
    """An alias may only exist once on a term."""
    term = make_term()
    term.collect_events()
    version = term.version

    with pytest.raises(DuplicateAliasError, match="bill"):
        term.add_alias("bill")

    assert term.version == version
    assert term.collect_events() == []


def test_blank_alias_is_rejected() -> None:
    """A blank alias is rejected before the aggregate mutates."""
    term = make_term()
    term.collect_events()

    with pytest.raises(InvalidAliasError, match="blank"):
        term.add_alias("")

    assert term.collect_events() == []


def test_removing_an_unknown_alias_is_rejected() -> None:
    """Removing an alias the term does not carry raises UnknownAliasError."""
    term = make_term(aliases=())

    with pytest.raises(UnknownAliasError, match="bill"):
        term.remove_alias("bill")


def test_approve_moves_a_draft_to_approved() -> None:
    """A draft can be approved once."""
    term = make_term()

    term.approve("reviewer")

    assert term.status is TermStatus.APPROVED


def test_reopen_moves_an_approved_term_back_to_draft() -> None:
    """Reopening makes an approved term editable again."""
    term = approved_term()

    term.reopen("fix wording")

    assert term.status is TermStatus.DRAFT


def test_deprecate_moves_an_approved_term_to_deprecated() -> None:
    """Only an approved term can be deprecated."""
    term = approved_term()

    term.deprecate("superseded")

    assert term.status is TermStatus.DEPRECATED


def test_reactivate_moves_a_deprecated_term_back_to_draft() -> None:
    """A deprecated term returns to draft before it can be edited again."""
    term = approved_term()
    term.deprecate("superseded")
    term.collect_events()

    term.reactivate("still used")

    assert term.status is TermStatus.DRAFT


@pytest.mark.parametrize(
    "command",
    [
        lambda term: term.reopen(),
        lambda term: term.deprecate(),
        lambda term: term.reactivate(),
    ],
)
def test_illegal_state_transitions_are_rejected(command: Any) -> None:
    """A transition from a draft that it does not accept raises InvalidTermStateError."""
    term = make_term()
    term.collect_events()

    with pytest.raises(InvalidTermStateError):
        command(term)


def test_approved_content_is_frozen_until_reopened() -> None:
    """Every content edit is rejected while the term is approved."""
    term = approved_term()
    target = uuid4()

    for command in (
        lambda: term.change_definition("other"),
        lambda: term.add_alias("other"),
        lambda: term.remove_alias("bill"),
        lambda: term.link(target, "table"),
        lambda: term.unlink(target, "table"),
    ):
        with pytest.raises(InvalidTermStateError, match="reopen"):
            command()

    term.reopen("fix wording")

    assert term.status is TermStatus.DRAFT


def test_rename_updates_name_and_path() -> None:
    """Renaming records both the new name and the new path."""
    term = make_term()
    term.collect_events()

    term.rename("bill", "finance/bill")

    assert (term.name, term.path) == ("bill", "finance/bill")
    event = term.collect_events()[-1]
    assert isinstance(event, Term.Renamed)
    assert (event.new_name, event.new_path) == ("bill", "finance/bill")


def test_rename_rejects_a_path_that_does_not_match_the_name() -> None:
    """A rename needs the parent path plus the new name."""
    term = make_term()
    term.collect_events()

    with pytest.raises(InvalidPathError, match="does not match"):
        term.rename("bill", "wrong/bill")

    assert term.collect_events() == []


def test_rename_is_allowed_for_approved_terms_but_not_deprecated_ones() -> None:
    """Renaming is metadata, so approved terms keep it; deprecated ones do not."""
    approved = approved_term()
    approved.rename("bill", "finance/bill")
    assert approved.path == "finance/bill"

    deprecated = approved_term()
    deprecated.deprecate()
    with pytest.raises(InvalidTermStateError, match="deprecated"):
        deprecated.rename("bill", "finance/bill")


def test_move_updates_parent_and_path() -> None:
    """Moving records the new parent and path."""
    term = make_term()
    new_parent = uuid4()
    term.collect_events()

    term.move(new_parent, "sales/invoice")

    assert (term.parent_id, term.path) == (new_parent, "sales/invoice")
    event = term.collect_events()[-1]
    assert isinstance(event, Term.Moved)
    assert event.parent_id == new_parent
    assert event.new_path == "sales/invoice"


def test_move_rejects_a_path_that_does_not_end_with_the_name() -> None:
    """A move may only receive a path for this term's name."""
    term = make_term()
    term.collect_events()

    with pytest.raises(InvalidPathError, match="does not end with"):
        term.move(uuid4(), "sales/other")

    assert term.collect_events() == []


def test_move_is_allowed_for_approved_terms_but_not_deprecated_ones() -> None:
    """Moving follows the same rule as renaming."""
    approved = approved_term()
    approved.move(uuid4(), "sales/invoice")
    assert approved.path == "sales/invoice"

    deprecated = approved_term()
    deprecated.deprecate()
    with pytest.raises(InvalidTermStateError, match="deprecated"):
        deprecated.move(None, "invoice")


def test_repath_changes_only_the_path_even_when_deprecated() -> None:
    """An ancestor change repaths a term in any live status."""
    term = approved_term()
    term.deprecate()
    term.collect_events()

    term.repath("sales/invoice")

    assert (term.name, term.path) == ("invoice", "sales/invoice")
    event = term.collect_events()[-1]
    assert isinstance(event, Term.Repathed)
    assert event.new_path == "sales/invoice"


def test_linking_records_each_target_once() -> None:
    """Links keep the kind, the id and the field name of their target."""
    term = make_term()
    table_id, catalog_id = uuid4(), uuid4()
    term.collect_events()

    term.link(table_id, "field", "customer_id")
    term.link(catalog_id, "catalog")
    term.link(catalog_id, "catalog")
    term.link(table_id, "field", "customer_id")

    assert set(term.links) == {
        TermLink(table_id, "field", "customer_id"),
        TermLink(catalog_id, "catalog"),
    }
    events = term.collect_events()
    assert [type(event) for event in events] == [Term.Linked, Term.Linked]


@pytest.mark.parametrize(
    ("kind", "field_name"),
    [("glossary", ""), ("field", ""), ("table", "field_name")],
)
def test_structurally_invalid_links_are_rejected(kind: str, field_name: str) -> None:
    """The kind and the field name must be consistent."""
    term = make_term()
    term.collect_events()

    with pytest.raises(InvalidLinkError):
        term.link(uuid4(), kind, field_name)

    assert term.collect_events() == []


def test_unlinking_an_unknown_target_is_rejected() -> None:
    """Removing a link the term does not carry raises UnknownLinkError."""
    term = make_term()

    with pytest.raises(UnknownLinkError, match="linked"):
        term.unlink(uuid4(), "catalog")


def test_discarding_a_term_blocks_every_command() -> None:
    """A discarded term rejects further mutations with DiscardedError."""
    term = make_term()
    term.discard()

    for command in (
        lambda: term.change_definition("other"),
        lambda: term.approve(),
        lambda: term.rename("other", "other"),
        lambda: term.repath("other"),
        lambda: term.discard(),
    ):
        with pytest.raises(DiscardedError, match="discarded"):
            command()


def test_replay_restores_content_position_status_aliases_and_links() -> None:
    """Replaying the collected events rebuilds the complete term."""
    term = make_term()
    new_parent = uuid4()
    table_id = uuid4()
    term.add_alias("invoice document")
    term.link(table_id, "field", "customer_id")
    term.move(new_parent, "sales/invoice")
    term.rename("bill", "sales/bill")
    term.approve()
    term.deprecate()

    replayed = replay(term.collect_events())

    assert replayed.definition == "A bill sent to a customer"
    assert replayed.aliases == {"bill": None, "invoice document": None}
    assert replayed.links == {TermLink(table_id, "field", "customer_id"): None}
    assert (replayed.parent_id, replayed.path) == (new_parent, "sales/bill")
    assert replayed.status is TermStatus.DEPRECATED


def test_a_term_starts_without_a_colour() -> None:
    """A term without an explicit colour renders in the default tone."""
    term = make_term()

    assert term.color == ""
    assert term.collect_events()[0].color == ""


@pytest.mark.parametrize(
    ("given", "expected"),
    [("#F2C811", "#f2c811"), (" #abc ", "#aabbcc"), ("", ""), (None, "")],
)
def test_the_start_colour_is_normalised(given: str | None, expected: str) -> None:
    """Short hex values are expanded and every colour is stored in lowercase."""
    term = Term(uuid4(), "invoice", "A bill", color=given)  # type: ignore[arg-type]

    assert term.color == expected


@pytest.mark.parametrize("color", ["yellow", "#12", "#12345", "f2c811", "#1234567"])
def test_invalid_colours_are_rejected(color: str) -> None:
    """Only a blank value or a #rgb/#rrggbb hex colour is accepted."""
    with pytest.raises(InvalidColorError):
        Term(uuid4(), "invoice", "A bill", color=color)


def test_changing_the_colour_records_the_event() -> None:
    """change_color normalises the value and records Term.ColorChanged."""
    term = make_term()
    term.collect_events()

    term.change_color("#ABC")

    assert term.color == "#aabbcc"
    events = term.collect_events()
    assert len(events) == 1
    assert isinstance(events[0], Term.ColorChanged)
    assert events[0].color == "#aabbcc"


def test_setting_the_same_colour_records_nothing() -> None:
    """A no-op colour change leaves the version and pending events untouched."""
    term = make_term(color="#f2c811")
    term.collect_events()
    version = term.version

    term.change_color("#f2c811")

    assert term.version == version
    assert term.collect_events() == []


def test_a_colour_can_be_cleared() -> None:
    """An empty value removes the colour again."""
    term = make_term(color="#f2c811")
    term.collect_events()

    term.change_color("")

    assert term.color == ""


def test_an_invalid_colour_leaves_the_term_unchanged() -> None:
    """Validation runs before the event is recorded."""
    term = make_term()
    term.collect_events()
    version = term.version

    with pytest.raises(InvalidColorError):
        term.change_color("blue")

    assert term.version == version
    assert term.collect_events() == []


def test_an_approved_term_can_be_recoloured() -> None:
    """Colour is presentation metadata, so the content freeze does not apply."""
    term = approved_term()

    term.change_color("#6bb700")

    assert term.color == "#6bb700"
    assert isinstance(term.collect_events()[0], Term.ColorChanged)


def test_a_deprecated_term_can_be_recoloured() -> None:
    """A deprecated term is still live, so its colour stays editable."""
    term = make_term()
    term.approve("reviewer")
    term.deprecate("superseded")
    term.collect_events()

    term.change_color("#d13438")

    assert term.color == "#d13438"


def test_a_discarded_term_cannot_be_recoloured() -> None:
    """Discarding closes every command, including the colour."""
    term = make_term()
    term.discard()

    with pytest.raises(DiscardedError):
        term.change_color("#f2c811")
