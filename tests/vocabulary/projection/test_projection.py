"""Tests for the vocabulary projection runner."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from etlalchemy.vocabulary.application import VocabularyApplication
from etlalchemy.vocabulary.projection.projection import run_vocabulary_projection
from tests.support import async_env, sqlite_url
from tests.vocabulary.support import FakeCatalogView


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    """Returns an environment backed by a temporary SQLite event store."""
    return async_env(sqlite_url(tmp_path / "events.db"))


async def write_vocabulary(
    env: dict[str, str],
    catalog_view: FakeCatalogView,
) -> tuple[UUID, UUID, int]:
    """Writes a small tree through the application and returns its ids."""
    table_id = uuid4()
    catalog_view.tables.add(table_id)
    async with VocabularyApplication(catalog_view=catalog_view, env=env) as app:
        domain_id = await app.create_domain("finance", "Finance vocabulary")
        revenue = await app.create_term(
            domain_id,
            "Revenue",
            "Recognized revenue",
            ["sales"],
        )
        await app.create_term(
            domain_id,
            "ARR",
            "Annual recurring revenue",
            parent="Revenue",
        )
        await app.create_term(
            domain_id,
            "MRR",
            "Monthly recurring revenue",
            parent="Revenue/ARR",
        )
        await app.link_term(domain_id, "Revenue/ARR", table_id, "table")
        await app.approve_term(domain_id, "Revenue/ARR", reviewer="alice")
        await app.rename_term(domain_id, "Revenue", "Sales")
        await app.move_term(domain_id, "Sales/ARR/MRR", None)
        await app.discard_term(domain_id, "Sales/ARR")
        # End on a single-stream term event so the last notification is a topic.
        await app.change_term_definition(domain_id, "MRR", "Monthly recurring revenue ")
        last = await app.recorder.max_notification_id()
    assert last is not None
    return domain_id, revenue, last


async def test_projection_materialises_the_tree(
    env: dict[str, str],
    catalog_view: FakeCatalogView,
) -> None:
    """The runner keeps the view in step with the application's notification log."""
    domain_id, revenue, last = await write_vocabulary(env, catalog_view)

    async with run_vocabulary_projection(env) as runner:
        await runner.wait(last, timeout=5.0)
        view: Any = runner.view

        domain = await view.get_domain(domain_id)
        assert domain is not None
        assert (domain.name, domain.description) == ("finance", "Finance vocabulary")
        rows = await view.list_terms(domain_id)
        assert [(row.path, row.parent_id) for row in rows] == [("MRR", None), ("Sales", None)]
        revenue_row = await view.get_term(revenue)
        assert revenue_row is not None
        assert (revenue_row.path, revenue_row.name) == ("Sales", "Sales")
        assert await view.list_aliases(revenue) == ["sales"]
        assert await view.find_term_id(domain_id, "Sales") == revenue
        assert await view.find_term_id(domain_id, "Sales/ARR") is None
        assert await view.max_tracking_id("vocabulary_application") == last


async def test_projection_writes_one_row_per_term(
    env: dict[str, str],
    catalog_view: FakeCatalogView,
) -> None:
    """Registry events never write; Term.Started is the only insert."""
    domain_id, _, last = await write_vocabulary(env, catalog_view)

    async with run_vocabulary_projection(env) as runner:
        await runner.wait(last, timeout=5.0)
        view: Any = runner.view

        assert len(await view.list_terms(domain_id)) == 2
        assert await view.list_children(domain_id, None) == await view.list_terms(domain_id)


async def test_projection_cascades_a_discarded_domain(
    env: dict[str, str],
    catalog_view: FakeCatalogView,
) -> None:
    """Discarding a domain removes the whole tree from the view."""
    async with VocabularyApplication(catalog_view=catalog_view, env=env) as app:
        domain_id = await app.create_domain("finance")
        root_id = await app.create_term(domain_id, "Revenue", "Recognized revenue")
        child_id = await app.create_term(domain_id, "ARR", "Annual recurring revenue", parent="Revenue")
        await app.discard_domain(domain_id)
        last = await app.recorder.max_notification_id()
    assert last is not None

    async with run_vocabulary_projection(env) as runner:
        await runner.wait(last, timeout=5.0)
        view: Any = runner.view

        assert await view.get_domain(domain_id) is None
        assert await view.get_term(root_id) is None
        assert await view.get_term(child_id) is None
        assert await view.list_terms(domain_id) == []


async def test_projection_stores_the_term_colour(
    env: dict[str, str],
    catalog_view: FakeCatalogView,
) -> None:
    """Term.Started carries the colour and Term.ColorChanged rewrites it."""
    async with VocabularyApplication(catalog_view=catalog_view, env=env) as app:
        domain_id = await app.create_domain("finance")
        coloured = await app.create_term(domain_id, "ARR", "Annual revenue", color="#F2C811")
        plain = await app.create_term(domain_id, "MRR", "Monthly revenue")
        await app.change_term_color(domain_id, plain, "#6bb700")
        last = await app.recorder.max_notification_id()
    assert last is not None

    async with run_vocabulary_projection(env) as runner:
        await runner.wait(last, timeout=5.0)
        view: Any = runner.view

        started = await view.get_term(coloured)
        changed = await view.get_term(plain)
        assert started is not None
        assert changed is not None
        assert (started.color, changed.color) == ("#f2c811", "#6bb700")
        hits = await view.search_terms("revenue")
        assert {hit.term_id: hit.color for hit in hits} == {
            coloured: "#f2c811",
            plain: "#6bb700",
        }
