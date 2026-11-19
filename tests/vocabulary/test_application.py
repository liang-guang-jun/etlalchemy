"""Tests for the vocabulary application use cases."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from etlalchemy.vocabulary.aggregates.errors import (
    CycleError,
    DiscardedError,
    DuplicateTermError,
    InvalidAliasError,
    InvalidColorError,
    InvalidLinkError,
    InvalidTermNameError,
    InvalidTermStateError,
    UnknownLinkError,
    UnknownParentError,
    UnknownTermError,
)
from etlalchemy.vocabulary.aggregates.term import Term
from etlalchemy.vocabulary.aggregates.types import TermLink, TermStatus
from etlalchemy.vocabulary.application import VocabularyApplication

from tests.vocabulary.support import FakeCatalogView


@pytest.fixture
def app(vocabulary_app: VocabularyApplication) -> VocabularyApplication:
    """Returns a started application backed by a temporary event store."""
    return vocabulary_app


async def create_tree(
    app: VocabularyApplication,
) -> tuple[UUID, UUID, UUID, UUID]:
    """Creates finance/Revenue, Revenue/ARR and Revenue/ARR/MRR."""
    domain_id = await app.create_domain("finance", "Finance vocabulary")
    revenue = await app.create_term(domain_id, "Revenue", "Recognized revenue")
    arr = await app.create_term(
        domain_id,
        "ARR",
        "Annual recurring revenue",
        parent="Revenue",
    )
    mrr = await app.create_term(
        domain_id,
        "MRR",
        "Monthly recurring revenue",
        parent="Revenue/ARR",
    )
    return domain_id, revenue, arr, mrr


async def test_create_domain_persists_a_started_event(app: VocabularyApplication) -> None:
    """create_domain() saves the new aggregate and returns its ID."""
    domain_id = await app.create_domain("finance", "Finance vocabulary")

    domain = await app.get_domain(domain_id)
    assert domain.name == "finance"
    assert domain.description == "Finance vocabulary"
    assert domain.version == 1


async def test_create_term_computes_the_path_and_registers_it(
    app: VocabularyApplication,
) -> None:
    """A root term uses its name; a child appends to the parent path."""
    domain_id, revenue, arr, mrr = await create_tree(app)

    domain = await app.get_domain(domain_id)
    assert domain.terms == {
        "Revenue": revenue,
        "Revenue/ARR": arr,
        "Revenue/ARR/MRR": mrr,
    }
    root = await app.get_term(domain_id, revenue)
    assert (root.parent_id, root.path) == (None, "Revenue")
    child = await app.get_term(domain_id, "Revenue/ARR")
    assert (child.parent_id, child.path) == (revenue, "Revenue/ARR")
    grandchild = await app.get_term(domain_id, mrr)
    assert (grandchild.parent_id, grandchild.path) == (arr, "Revenue/ARR/MRR")


async def test_duplicate_paths_are_rejected(app: VocabularyApplication) -> None:
    """The domain registry owns path uniqueness."""
    domain_id, _, _, _ = await create_tree(app)
    version = (await app.get_domain(domain_id)).version
    first = await app.get_term(domain_id, "Revenue")

    with pytest.raises(DuplicateTermError, match="Revenue"):
        await app.create_term(domain_id, "Revenue", "Another revenue")
    with pytest.raises(DuplicateTermError, match="Revenue/ARR"):
        await app.create_term(domain_id, "ARR", "Another ARR", parent="Revenue")

    assert (await app.get_domain(domain_id)).version == version
    assert (await app.get_term(domain_id, "Revenue")).path == first.path


async def test_terms_are_addressable_by_path_or_id(app: VocabularyApplication) -> None:
    """The ids returned by create stay valid next to the full paths."""
    domain_id, revenue, arr, _ = await create_tree(app)

    assert (await app.get_term(domain_id, "Revenue/ARR")).id == arr
    assert (await app.get_term(domain_id, arr)).id == arr
    assert (await app.get_term(domain_id, "Revenue")).id == revenue

    with pytest.raises(UnknownTermError, match="ARR"):
        await app.get_term(domain_id, "ARR")


async def test_invalid_names_are_rejected(app: VocabularyApplication) -> None:
    """A name must be one non-blank path segment."""
    domain_id = await app.create_domain("finance")

    with pytest.raises(InvalidTermNameError, match="blank"):
        await app.create_term(domain_id, " ", "A definition")
    with pytest.raises(InvalidTermNameError, match="'/'"):
        await app.create_term(domain_id, "Revenue/ARR", "A definition")


async def test_an_unknown_explicit_parent_is_reported_as_such(
    app: VocabularyApplication,
) -> None:
    """A missing parent is distinct from a missing term."""
    domain_id = await app.create_domain("finance")

    with pytest.raises(UnknownParentError, match="Missing"):
        await app.create_term(domain_id, "ARR", "A definition", parent="Missing")


async def test_rename_cascades_to_every_descendant(app: VocabularyApplication) -> None:
    """Renaming a term repaths the whole subtree in one unit of work."""
    domain_id, revenue, arr, mrr = await create_tree(app)

    await app.rename_term(domain_id, "Revenue", "Sales")

    assert (await app.get_term(domain_id, revenue)).path == "Sales"
    assert (await app.get_term(domain_id, arr)).path == "Sales/ARR"
    assert (await app.get_term(domain_id, mrr)).path == "Sales/ARR/MRR"
    assert (await app.get_domain(domain_id)).terms == {
        "Sales": revenue,
        "Sales/ARR": arr,
        "Sales/ARR/MRR": mrr,
    }
    with pytest.raises(UnknownTermError):
        await app.get_term(domain_id, "Revenue")


async def test_rename_collision_leaves_the_tree_untouched(
    app: VocabularyApplication,
) -> None:
    """A path collision aborts the command before any term is changed."""
    domain_id, revenue, arr, mrr = await create_tree(app)
    await app.create_term(domain_id, "Sales", "Sales revenue")
    versions = [
        (await app.repository.get(term_id)).version for term_id in (revenue, arr, mrr)
    ]

    with pytest.raises(DuplicateTermError, match="Sales"):
        await app.rename_term(domain_id, "Revenue", "Sales")

    assert [(await app.repository.get(term_id)).path for term_id in (revenue, arr, mrr)] == [
        "Revenue",
        "Revenue/ARR",
        "Revenue/ARR/MRR",
    ]
    assert [
        (await app.repository.get(term_id)).version for term_id in (revenue, arr, mrr)
    ] == versions


async def test_move_cascades_and_can_return_to_the_top_level(
    app: VocabularyApplication,
) -> None:
    """Moving a subtree keeps its shape under the new parent."""
    domain_id, revenue, arr, mrr = await create_tree(app)

    await app.move_term(domain_id, "Revenue/ARR", "Revenue")

    assert (await app.get_term(domain_id, arr)).path == "Revenue/ARR"
    await app.move_term(domain_id, arr, None)
    assert (await app.get_term(domain_id, arr)).path == "ARR"
    assert (await app.get_term(domain_id, mrr)).path == "ARR/MRR"
    assert (await app.get_term(domain_id, arr)).parent_id is None


async def test_move_rejects_a_cycle(app: VocabularyApplication) -> None:
    """A term cannot move under itself or one of its descendants."""
    domain_id, revenue, _, _ = await create_tree(app)

    with pytest.raises(CycleError):
        await app.move_term(domain_id, "Revenue", "Revenue")
    with pytest.raises(CycleError):
        await app.move_term(domain_id, "Revenue", "Revenue/ARR")


async def test_discard_term_cascades_and_emits_one_event_per_term(
    app: VocabularyApplication,
) -> None:
    """Every descendant is discarded and unregistered."""
    domain_id, revenue, arr, mrr = await create_tree(app)

    await app.discard_term(domain_id, "Revenue")

    assert (await app.get_domain(domain_id)).terms == {}
    for term_id in (revenue, arr, mrr):
        loaded: Term = await app.repository.get(term_id)
        assert loaded.version > 1
        with pytest.raises(DiscardedError):
            loaded.change_definition("other")
    with pytest.raises(UnknownTermError):
        await app.get_term(domain_id, "ARR")


async def test_discard_domain_emits_a_single_event(
    app: VocabularyApplication,
) -> None:
    """Discarding a domain leaves the term aggregates untouched."""
    domain_id, revenue, _, _ = await create_tree(app)
    version = (await app.repository.get(revenue)).version

    await app.discard_domain(domain_id)

    with pytest.raises(DiscardedError):
        await app.create_term(domain_id, "Forecast", "A forecast")
    assert (await app.repository.get(revenue)).version == version


async def test_status_flow_controls_content_edits(app: VocabularyApplication) -> None:
    """Content changes require reopening or reactivating the term first."""
    domain_id, _, arr, _ = await create_tree(app)

    await app.approve_term(domain_id, "Revenue/ARR", reviewer="alice")
    assert (await app.get_term(domain_id, arr)).status is TermStatus.APPROVED

    with pytest.raises(InvalidTermStateError, match="reopen"):
        await app.change_term_definition(domain_id, "Revenue/ARR", "other")

    await app.reopen_term(domain_id, "Revenue/ARR", reason="fix")
    await app.change_term_definition(domain_id, "Revenue/ARR", "Annual recurring revenue ")
    await app.approve_term(domain_id, "Revenue/ARR")
    await app.deprecate_term(domain_id, "Revenue/ARR", reason="superseded")
    assert (await app.get_term(domain_id, arr)).status is TermStatus.DEPRECATED

    await app.reactivate_term(domain_id, "Revenue/ARR", reason="still used")
    assert (await app.get_term(domain_id, arr)).status is TermStatus.DRAFT


async def test_aliases_can_be_added_and_removed(app: VocabularyApplication) -> None:
    """Alias commands work on draft terms and normalise their input."""
    domain_id = await app.create_domain("finance")
    term_id = await app.create_term(domain_id, "invoice", "A bill")

    await app.add_term_alias(domain_id, term_id, " bill ")
    await app.add_term_alias(domain_id, term_id, "invoice document")
    await app.remove_term_alias(domain_id, term_id, "bill")

    term = await app.get_term(domain_id, term_id)
    assert term.aliases == {"invoice document": None}


async def test_blank_aliases_are_rejected(app: VocabularyApplication) -> None:
    """A blank alias never reaches the aggregate."""
    domain_id = await app.create_domain("finance")

    with pytest.raises(InvalidAliasError, match="blank"):
        await app.create_term(domain_id, "invoice", "A bill", [" "])


async def test_link_term_validates_the_catalog_target(
    app: VocabularyApplication,
    catalog_view: FakeCatalogView,
) -> None:
    """Every target kind is checked against the catalog read model."""
    catalog_id, schema_id, table_id = uuid4(), uuid4(), uuid4()
    catalog_view.catalogs.add(catalog_id)
    catalog_view.schemas.add(schema_id)
    catalog_view.tables.add(table_id)
    catalog_view.fields[table_id] = {"customer_id"}
    domain_id = await app.create_domain("finance")
    await app.create_term(domain_id, "invoice", "A bill")

    await app.link_term(domain_id, "invoice", catalog_id, "catalog")
    await app.link_term(domain_id, "invoice", schema_id, "schema")
    await app.link_term(domain_id, "invoice", table_id, "table")
    await app.link_term(domain_id, "invoice", table_id, "field", "customer_id")

    term = await app.get_term(domain_id, "invoice")
    assert set(term.links) == {
        TermLink(catalog_id, "catalog"),
        TermLink(schema_id, "schema"),
        TermLink(table_id, "table"),
        TermLink(table_id, "field", "customer_id"),
    }


async def test_link_term_rejects_missing_targets(
    app: VocabularyApplication,
    catalog_view: FakeCatalogView,
) -> None:
    """An unknown object or field is rejected before the aggregate mutates."""
    table_id = uuid4()
    catalog_view.tables.add(table_id)
    domain_id = await app.create_domain("finance")
    await app.create_term(domain_id, "invoice", "A bill")
    version = (await app.get_term(domain_id, "invoice")).version

    with pytest.raises(UnknownLinkError, match="Catalog"):
        await app.link_term(domain_id, "invoice", uuid4(), "catalog")
    with pytest.raises(UnknownLinkError, match="Field"):
        await app.link_term(domain_id, "invoice", table_id, "field", "missing")
    with pytest.raises(InvalidLinkError, match="unknown target_kind"):
        await app.link_term(domain_id, "invoice", table_id, "glossary")

    assert (await app.get_term(domain_id, "invoice")).version == version


async def test_unlink_term_removes_the_link(
    app: VocabularyApplication,
    catalog_view: FakeCatalogView,
) -> None:
    """A recorded link can be removed again."""
    table_id = uuid4()
    catalog_view.tables.add(table_id)
    domain_id = await app.create_domain("finance")
    await app.create_term(domain_id, "invoice", "A bill")
    await app.link_term(domain_id, "invoice", table_id, "table")

    await app.unlink_term(domain_id, "invoice", table_id, "table")

    assert (await app.get_term(domain_id, "invoice")).links == {}


async def test_create_term_stores_a_normalised_colour(app: VocabularyApplication) -> None:
    """The creation event and the aggregate both carry the canonical colour."""
    domain_id = await app.create_domain("finance")
    term_id = await app.create_term(domain_id, "ARR", "Annual revenue", color="#AbC")

    term = await app.get_term(domain_id, term_id)
    assert term.color == "#aabbcc"
    events = list(await app.events.get(term_id))
    started = [event for event in events if isinstance(event, Term.Started)]
    assert started[0].color == "#aabbcc"


async def test_create_term_rejects_an_invalid_colour(app: VocabularyApplication) -> None:
    """A malformed colour aborts the creation before anything is saved."""
    domain_id = await app.create_domain("finance")

    with pytest.raises(InvalidColorError):
        await app.create_term(domain_id, "ARR", "Annual revenue", color="amber")

    domain = await app.get_domain(domain_id)
    assert domain.terms == {}


async def test_change_term_color_persists_the_event(app: VocabularyApplication) -> None:
    """change_term_color() records the new colour in lowercase."""
    domain_id, revenue, _, _ = await create_tree(app)

    await app.change_term_color(domain_id, revenue, "#6BB700")

    term = await app.get_term(domain_id, revenue)
    assert term.color == "#6bb700"
    events = list(await app.events.get(revenue))
    changed = [event for event in events if isinstance(event, Term.ColorChanged)]
    assert [event.color for event in changed] == ["#6bb700"]


async def test_change_term_color_works_on_an_approved_term(
    app: VocabularyApplication,
) -> None:
    """Colour is metadata, so approving the term does not freeze it."""
    domain_id, revenue, _, _ = await create_tree(app)
    await app.approve_term(domain_id, revenue)

    await app.change_term_color(domain_id, revenue, "#f2c811")

    assert (await app.get_term(domain_id, revenue)).color == "#f2c811"


async def test_change_term_color_rejects_an_unknown_term(
    app: VocabularyApplication,
) -> None:
    """Colour changes address the term like every other term command."""
    domain_id, _, _, _ = await create_tree(app)

    with pytest.raises(UnknownTermError):
        await app.change_term_color(domain_id, uuid4(), "#f2c811")
