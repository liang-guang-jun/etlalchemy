"""Tests for the SQLite vocabulary read model."""

from __future__ import annotations

import itertools
from collections.abc import Callable, Sequence
from uuid import UUID, uuid4

import pytest
from etlalchemy.vocabulary.projection.sqlalchemy import SQLAlchemyVocabularyView
from etlalchemy.vocabulary.projection.view import (
    DomainRow,
    TermLinkRow,
    TermRow,
)
from eventsourcing.persistence import Tracking
from sqlalchemy.exc import IntegrityError

UPSTREAM = "vocabulary-application"

TrackingFactory = Callable[[], Tracking]


@pytest.fixture
def view(vocabulary_view: SQLAlchemyVocabularyView) -> SQLAlchemyVocabularyView:
    """Returns an empty view backed by a temporary database file."""
    return vocabulary_view


@pytest.fixture
def tracking() -> TrackingFactory:
    """Returns a factory of monotonically increasing tracking records."""
    counter = itertools.count(1)
    return lambda: Tracking(UPSTREAM, next(counter))


async def register_domain(
    view: SQLAlchemyVocabularyView,
    tracking: Tracking,
    name: str = "finance",
    description: str = "",
) -> UUID:
    """Registers a domain in the view and returns its ID."""
    domain_id = uuid4()
    await view.register_domain(domain_id, name, description, tracking)
    return domain_id


async def register_term(
    view: SQLAlchemyVocabularyView,
    tracking: Tracking,
    domain_id: UUID,
    path: str,
    *,
    parent_id: UUID | None = None,
    definition: str = "A definition",
    aliases: Sequence[str] = (),
) -> UUID:
    """Registers a term in the view and returns its ID."""
    term_id = uuid4()
    await view.register_term(
        term_id,
        domain_id,
        parent_id,
        path,
        path.rpartition("/")[2],
        definition,
        list(aliases),
        tracking,
    )
    return term_id


async def test_create_table_is_idempotent(view: SQLAlchemyVocabularyView) -> None:
    """Creating the view tables twice does not fail."""
    await view.create_table()
    await view.create_table()


async def test_register_domain_stores_the_row_and_tracks_the_event(
    view: SQLAlchemyVocabularyView,
    tracking: TrackingFactory,
) -> None:
    """A registered domain is queryable by id and listed by name."""
    domain_id = await register_domain(view, tracking(), "finance", "Finance vocabulary")

    assert await view.get_domain(domain_id) == DomainRow(
        domain_id,
        "finance",
        "Finance vocabulary",
    )
    assert [row.domain_id for row in await view.list_domains()] == [domain_id]
    assert await view.max_tracking_id(UPSTREAM) == 1


async def test_change_domain_updates_only_the_given_attributes(
    view: SQLAlchemyVocabularyView,
    tracking: TrackingFactory,
) -> None:
    """A description-only change keeps the name."""
    domain_id = await register_domain(view, tracking(), "finance", "Finance vocabulary")

    await view.change_domain(domain_id, None, "FP&A vocabulary", tracking())

    row = await view.get_domain(domain_id)
    assert row is not None
    assert (row.name, row.description) == ("finance", "FP&A vocabulary")


async def test_register_term_stores_path_parent_and_aliases(
    view: SQLAlchemyVocabularyView,
    tracking: TrackingFactory,
) -> None:
    """A registered term starts as a draft at its path."""
    domain_id = await register_domain(view, tracking())
    root_id = await register_term(view, tracking(), domain_id, "Revenue")
    child_id = await register_term(
        view,
        tracking(),
        domain_id,
        "Revenue/ARR",
        parent_id=root_id,
        aliases=["arr", "annual recurring revenue"],
    )

    assert await view.get_term(root_id) == TermRow(
        root_id,
        domain_id,
        None,
        "Revenue",
        "Revenue",
        "A definition",
        "draft",
    )
    row = await view.get_term(child_id)
    assert row is not None
    assert (row.parent_id, row.path, row.name) == (root_id, "Revenue/ARR", "ARR")
    assert await view.list_aliases(child_id) == ["annual recurring revenue", "arr"]
    assert await view.find_term_id(domain_id, "Revenue/ARR") == child_id


async def test_path_commands_update_their_own_row(
    view: SQLAlchemyVocabularyView,
    tracking: TrackingFactory,
) -> None:
    """Rename, move and repath each change only the addressed term."""
    domain_id = await register_domain(view, tracking())
    root_id = await register_term(view, tracking(), domain_id, "Revenue")
    child_id = await register_term(
        view,
        tracking(),
        domain_id,
        "Revenue/ARR",
        parent_id=root_id,
    )

    await view.rename_term(root_id, "Sales", "Sales", tracking())
    await view.repath_term(child_id, "Sales/ARR", tracking())
    await view.move_term(child_id, None, "ARR", tracking())

    root = await view.get_term(root_id)
    child = await view.get_term(child_id)
    assert root is not None and child is not None
    assert (root.name, root.path) == ("Sales", "Sales")
    assert (child.parent_id, child.path) == (None, "ARR")


async def test_list_terms_filters_by_status_and_pages(
    view: SQLAlchemyVocabularyView,
    tracking: TrackingFactory,
) -> None:
    """list_terms is ordered by path and supports filters and paging."""
    domain_id = await register_domain(view, tracking())
    root_id = await register_term(view, tracking(), domain_id, "Revenue")
    first = await register_term(view, tracking(), domain_id, "Revenue/ARR", parent_id=root_id)
    second = await register_term(view, tracking(), domain_id, "Revenue/MRR", parent_id=root_id)
    await view.set_term_status(second, "approved", tracking())

    assert [row.term_id for row in await view.list_terms(domain_id)] == [
        root_id,
        first,
        second,
    ]
    assert [row.term_id for row in await view.list_terms(domain_id, status="approved")] == [
        second
    ]
    assert [row.term_id for row in await view.list_terms(domain_id, limit=1, offset=1)] == [
        first
    ]


async def test_list_children_returns_one_level(
    view: SQLAlchemyVocabularyView,
    tracking: TrackingFactory,
) -> None:
    """Top-level terms and direct children are addressable separately."""
    domain_id = await register_domain(view, tracking())
    root_id = await register_term(view, tracking(), domain_id, "Revenue")
    arr = await register_term(view, tracking(), domain_id, "Revenue/ARR", parent_id=root_id)
    await register_term(view, tracking(), domain_id, "Revenue/ARR/MRR", parent_id=arr)
    other_root = await register_term(view, tracking(), domain_id, "Sales")

    assert [row.term_id for row in await view.list_children(domain_id, None)] == [
        root_id,
        other_root,
    ]
    assert [row.term_id for row in await view.list_children(domain_id, root_id)] == [arr]
    assert [row.term_id for row in await view.list_children(domain_id, arr)] != []


async def test_list_descendants_orders_the_subtree_by_path(
    view: SQLAlchemyVocabularyView,
    tracking: TrackingFactory,
) -> None:
    """Descendants are returned parents first and exclude siblings."""
    domain_id = await register_domain(view, tracking())
    root_id = await register_term(view, tracking(), domain_id, "Revenue")
    arr = await register_term(view, tracking(), domain_id, "Revenue/ARR", parent_id=root_id)
    mrr = await register_term(view, tracking(), domain_id, "Revenue/ARR/MRR", parent_id=arr)
    sibling = await register_term(view, tracking(), domain_id, "Revenue/MRR", parent_id=root_id)

    rows = await view.list_descendants(domain_id, root_id)

    assert [row.term_id for row in rows] == [arr, mrr, sibling]
    assert await view.list_descendants(domain_id, mrr) == []


@pytest.mark.parametrize("root_path", ["Rev_2024", "Rev%2024"])
async def test_list_descendants_escapes_like_wildcards(
    view: SQLAlchemyVocabularyView,
    tracking: TrackingFactory,
    root_path: str,
) -> None:
    """A wildcard in a path never matches unrelated siblings."""
    domain_id = await register_domain(view, tracking())
    wildcard_root = await register_term(view, tracking(), domain_id, root_path)
    child = await register_term(
        view,
        tracking(),
        domain_id,
        f"{root_path}/ARR",
        parent_id=wildcard_root,
    )
    other_root = await register_term(
        view,
        tracking(),
        domain_id,
        root_path.replace("_", "X").replace("%", "X"),
    )
    await register_term(
        view,
        tracking(),
        domain_id,
        f"{other_root}/ARR",
        parent_id=other_root,
    )

    assert [row.term_id for row in await view.list_descendants(domain_id, wildcard_root)] == [
        child
    ]


async def test_aliases_are_idempotent(view: SQLAlchemyVocabularyView, tracking: TrackingFactory) -> None:
    """Adding an existing alias does nothing; removing it drops it."""
    domain_id = await register_domain(view, tracking())
    term_id = await register_term(view, tracking(), domain_id, "invoice", aliases=["bill"])

    await view.add_term_alias(term_id, "bill", tracking())
    await view.add_term_alias(term_id, "invoice document", tracking())
    await view.remove_term_alias(term_id, "bill", tracking())

    assert await view.list_aliases(term_id) == ["invoice document"]


async def test_term_content_and_status_commands(
    view: SQLAlchemyVocabularyView,
    tracking: TrackingFactory,
) -> None:
    """Definition, name and status are updated in place."""
    domain_id = await register_domain(view, tracking())
    term_id = await register_term(view, tracking(), domain_id, "invoice")

    await view.change_term_definition(term_id, "A bill to a customer", tracking())
    await view.rename_term(term_id, "bill", "bill", tracking())
    await view.set_term_status(term_id, "approved", tracking())

    row = await view.get_term(term_id)
    assert row is not None
    assert (row.name, row.definition, row.status) == (
        "bill",
        "A bill to a customer",
        "approved",
    )


async def test_links_are_recorded_and_removed(
    view: SQLAlchemyVocabularyView,
    tracking: TrackingFactory,
) -> None:
    """A term keeps one row per distinct link."""
    domain_id = await register_domain(view, tracking())
    term_id = await register_term(view, tracking(), domain_id, "invoice")
    table_id, catalog_id = uuid4(), uuid4()

    await view.link_term(term_id, table_id, "field", "customer_id", tracking())
    await view.link_term(term_id, catalog_id, "catalog", "", tracking())
    await view.link_term(term_id, catalog_id, "catalog", "", tracking())

    assert await view.list_links(term_id) == [
        TermLinkRow(catalog_id, "catalog", ""),
        TermLinkRow(table_id, "field", "customer_id"),
    ]

    await view.unlink_term(term_id, catalog_id, "catalog", "", tracking())

    assert await view.list_links(term_id) == [TermLinkRow(table_id, "field", "customer_id")]


async def test_terms_for_target_and_table(
    view: SQLAlchemyVocabularyView,
    tracking: TrackingFactory,
) -> None:
    """Reverse lookups return the linked terms once, even for several fields."""
    domain_id = await register_domain(view, tracking())
    term_id = await register_term(view, tracking(), domain_id, "invoice")
    other_id = await register_term(view, tracking(), domain_id, "customer")
    table_id = uuid4()
    await view.link_term(term_id, table_id, "table", "", tracking())
    await view.link_term(term_id, table_id, "field", "customer_id", tracking())
    await view.link_term(term_id, table_id, "field", "invoice_id", tracking())
    await view.link_term(other_id, table_id, "field", "customer_id", tracking())

    assert [row.term_id for row in await view.terms_for_target(table_id, "table")] == [term_id]
    assert [
        row.term_id for row in await view.terms_for_target(table_id, "field", "customer_id")
    ] == [other_id, term_id]
    assert [row.term_id for row in await view.terms_for_table(table_id)] == [other_id, term_id]


async def test_search_terms_matches_name_definition_and_alias(
    view: SQLAlchemyVocabularyView,
    tracking: TrackingFactory,
) -> None:
    """Search finds all three sources and reports the matched alias once."""
    domain_id = await register_domain(view, tracking(), "finance")
    invoice_id = await register_term(
        view,
        tracking(),
        domain_id,
        "Revenue/invoice",
        definition="A bill sent to a customer",
        aliases=["bill", "billing document"],
    )
    receipt_id = await register_term(
        view,
        tracking(),
        domain_id,
        "Revenue/receipt",
        definition="Proof of payment",
    )

    by_definition = await view.search_terms("customer")
    by_alias = await view.search_terms("bill")
    by_definition_two = await view.search_terms("payment")

    assert [row.term_id for row in by_definition] == [invoice_id]
    assert by_definition[0].matched_alias is None
    assert [row.term_id for row in by_alias] == [invoice_id]
    assert by_alias[0].matched_alias == "bill"
    assert [row.term_id for row in by_definition_two] == [receipt_id]
    assert by_alias[0].term_path == "Revenue/invoice"


async def test_search_terms_honours_the_filters_and_limit(
    view: SQLAlchemyVocabularyView,
    tracking: TrackingFactory,
) -> None:
    """Domain, status and limit narrow the result set."""
    finance = await register_domain(view, tracking(), "finance")
    sales = await register_domain(view, tracking(), "sales")
    first = await register_term(view, tracking(), finance, "Revenue/alpha", definition="shared")
    second = await register_term(view, tracking(), finance, "Revenue/beta", definition="shared")
    await register_term(view, tracking(), sales, "Revenue/gamma", definition="shared")
    await view.set_term_status(second, "approved", tracking())

    assert len(await view.search_terms("shared")) == 3
    assert len(await view.search_terms("shared", domain_id=finance)) == 2
    assert [
        row.term_id for row in await view.search_terms("shared", domain_id=finance, status="draft")
    ] == [first]
    assert len(await view.search_terms("shared", limit=1)) == 1


async def test_search_terms_treats_wildcards_literally(
    view: SQLAlchemyVocabularyView,
    tracking: TrackingFactory,
) -> None:
    """A query containing % or _ matches those characters, not any character."""
    domain_id = await register_domain(view, tracking())
    percent = await register_term(
        view,
        tracking(),
        domain_id,
        "Revenue/percent",
        definition="100% recurring",
        aliases=["pct_share"],
    )
    await register_term(
        view,
        tracking(),
        domain_id,
        "Revenue/plain",
        definition="flat fee",
        aliases=["share"],
    )

    assert [row.term_id for row in await view.search_terms("%")] == [percent]
    assert [row.term_id for row in await view.search_terms("_")] == [percent]


async def test_the_unique_index_rejects_a_duplicate_live_path(
    view: SQLAlchemyVocabularyView,
    tracking: TrackingFactory,
) -> None:
    """The partial unique index backs the aggregate registry."""
    domain_id = await register_domain(view, tracking())
    await register_term(view, tracking(), domain_id, "Revenue")

    with pytest.raises(IntegrityError):
        await register_term(view, tracking(), domain_id, "Revenue")

    other_domain = await register_domain(view, tracking(), "sales")
    await register_term(view, tracking(), other_domain, "Revenue")


async def test_discarding_one_term_keeps_its_children(
    view: SQLAlchemyVocabularyView,
    tracking: TrackingFactory,
) -> None:
    """The view command is self-only; the application decides the cascade."""
    domain_id = await register_domain(view, tracking())
    root_id = await register_term(view, tracking(), domain_id, "Revenue")
    child_id = await register_term(
        view,
        tracking(),
        domain_id,
        "Revenue/ARR",
        parent_id=root_id,
        aliases=["arr"],
    )
    await view.link_term(child_id, uuid4(), "catalog", "", tracking())

    await view.discard_term(root_id, tracking())

    assert await view.get_term(root_id) is None
    assert await view.get_term(child_id) is not None
    assert await view.list_aliases(child_id) == ["arr"]


async def test_a_discarded_path_can_be_reused(
    view: SQLAlchemyVocabularyView,
    tracking: TrackingFactory,
) -> None:
    """The partial index only covers live rows."""
    domain_id = await register_domain(view, tracking())
    term_id = await register_term(view, tracking(), domain_id, "Revenue")

    await view.discard_term(term_id, tracking())
    await register_term(view, tracking(), domain_id, "Revenue")

    rows = await view.list_terms(domain_id)
    assert [row.path for row in rows] == ["Revenue"]
    assert rows[0].term_id != term_id


async def test_discarding_a_domain_cascades(
    view: SQLAlchemyVocabularyView,
    tracking: TrackingFactory,
) -> None:
    """Discarding a domain hides the whole tree."""
    domain_id = await register_domain(view, tracking())
    root_id = await register_term(view, tracking(), domain_id, "Revenue")
    child_id = await register_term(
        view,
        tracking(),
        domain_id,
        "Revenue/ARR",
        parent_id=root_id,
        aliases=["arr"],
    )
    await view.link_term(child_id, uuid4(), "catalog", "", tracking())

    await view.discard_domain(domain_id, tracking())

    assert await view.get_domain(domain_id) is None
    assert await view.get_term(root_id) is None
    assert await view.get_term(child_id) is None
    assert await view.list_aliases(child_id) == []
    assert await view.list_links(child_id) == []
    assert await view.list_domains() == []


async def test_set_term_color_updates_the_row(
    view: SQLAlchemyVocabularyView,
    tracking: TrackingFactory,
) -> None:
    """set_term_color() rewrites only the colour column."""
    domain_id = await register_domain(view, tracking())
    term_id = await register_term(view, tracking(), domain_id, "Revenue")

    await view.set_term_color(term_id, "#f2c811", tracking())

    row = await view.get_term(term_id)
    assert row is not None
    assert row.color == "#f2c811"
    assert row.path == "Revenue"
