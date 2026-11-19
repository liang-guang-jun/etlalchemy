"""Integration tests for the PostgreSQL vocabulary read model.

These tests need a running PostgreSQL database. Point `TEST_DATABASE_URL` (or
`ETLALCHEMY_DSN`) at it, for example:

    docker compose -f docker/docker-compose.yml up -d --wait
    export TEST_DATABASE_URL=postgresql://etlalchemy:etlalchemy@localhost:55432/etlalchemy_test
"""

from __future__ import annotations

import itertools
import os
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
from etlalchemy.vocabulary.projection.sqlalchemy import SQLAlchemyVocabularyView
from eventsourcing.asyncio.sqlalchemy import AsyncSQLAlchemyDatastore
from eventsourcing.persistence import Tracking
from sqlalchemy.exc import IntegrityError

from tests.support import async_postgres_url

DSN = os.environ.get("TEST_DATABASE_URL") or os.environ.get("ETLALCHEMY_DSN")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DSN, reason="TEST_DATABASE_URL is not set"),
]

VIEW_TABLES = (
    "vocabulary_domains",
    "vocabulary_terms",
    "vocabulary_term_aliases",
    "vocabulary_term_links",
    "vocabulary_projection_tracking",
)

UPSTREAM = "vocabulary-application"


async def drop_tables(datastore: AsyncSQLAlchemyDatastore) -> None:
    """Drops the vocabulary tables so every test starts from an empty read model."""
    async with datastore.engine.begin() as conn:
        for table in VIEW_TABLES:
            await conn.exec_driver_sql(f'DROP TABLE IF EXISTS "{table}" CASCADE')


@pytest.fixture
async def view() -> AsyncIterator[SQLAlchemyVocabularyView]:
    """Returns a PostgreSQL view whose tables were just created."""
    datastore = AsyncSQLAlchemyDatastore(async_postgres_url(DSN or ""))
    await drop_tables(datastore)
    vocabulary_view = SQLAlchemyVocabularyView(
        datastore=datastore,
        tracking_table=datastore.create_tracking_table("vocabulary_projection_tracking"),
    )
    await vocabulary_view.create_table()
    try:
        yield vocabulary_view
    finally:
        await datastore.close()


async def register(
    view: SQLAlchemyVocabularyView,
    tracking: Tracking,
    domain_id: UUID,
    path: str,
    *,
    parent_id: UUID | None = None,
    aliases: list[str] | None = None,
) -> UUID:
    """Registers one term in the PostgreSQL view."""
    term_id = uuid4()
    await view.register_term(
        term_id,
        domain_id,
        parent_id,
        path,
        path.rpartition("/")[2],
        "A definition",
        aliases or [],
        tracking,
    )
    return term_id


async def test_tree_queries_aliases_links_and_search(
    view: SQLAlchemyVocabularyView,
) -> None:
    """The PostgreSQL view stores and queries the whole tree."""
    counter = itertools.count(1)
    tracking = lambda: Tracking(UPSTREAM, next(counter))  # noqa: E731

    domain_id, table_id = uuid4(), uuid4()
    await view.register_domain(domain_id, "finance", "", tracking())
    root = await register(view, tracking(), domain_id, "Rev_2024", aliases=["revenue"])
    child = await register(view, tracking(), domain_id, "Rev_2024/ARR", parent_id=root)
    await view.link_term(child, table_id, "field", "customer_id", tracking())

    assert await view.find_term_id(domain_id, "Rev_2024/ARR") == child
    assert [row.term_id for row in await view.list_children(domain_id, root)] == [child]
    assert [row.term_id for row in await view.list_descendants(domain_id, root)] == [child]
    assert await view.list_aliases(root) == ["revenue"]
    results = await view.search_terms("revenue")
    assert [(row.term_id, row.matched_alias) for row in results] == [(root, "revenue")]
    assert [row.term_id for row in await view.terms_for_target(table_id, "field", "customer_id")] == [
        child
    ]


async def test_the_partial_unique_index_rejects_a_duplicate_live_path(
    view: SQLAlchemyVocabularyView,
) -> None:
    """The PostgreSQL index backs the aggregate registry."""
    counter = itertools.count(1)
    tracking = lambda: Tracking(UPSTREAM, next(counter))  # noqa: E731

    domain_id = uuid4()
    await view.register_domain(domain_id, "finance", "", tracking())
    term_id = await register(view, tracking(), domain_id, "Revenue")

    with pytest.raises(IntegrityError):
        await register(view, tracking(), domain_id, "Revenue")

    await view.discard_term(term_id, tracking())
    await register(view, tracking(), domain_id, "Revenue")


async def test_discarding_a_domain_cascades(
    view: SQLAlchemyVocabularyView,
) -> None:
    """Discarding a domain hides its whole tree."""
    counter = itertools.count(1)
    tracking = lambda: Tracking(UPSTREAM, next(counter))  # noqa: E731

    domain_id = uuid4()
    await view.register_domain(domain_id, "finance", "", tracking())
    root = await register(view, tracking(), domain_id, "Revenue")
    child = await register(view, tracking(), domain_id, "Revenue/ARR", parent_id=root)

    await view.discard_domain(domain_id, tracking())

    assert await view.get_domain(domain_id) is None
    assert await view.get_term(root) is None
    assert await view.get_term(child) is None
