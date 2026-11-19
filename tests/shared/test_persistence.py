"""Tests of the shared read-model persistence helpers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from etlalchemy.shared.persistence import AsyncCoreView, ensure_column, utc_now
from eventsourcing.asyncio.sqlalchemy import AsyncSQLAlchemyDatastore
from sqlalchemy import Column, MetaData, String, Table, select

UPSTREAM = "test_application"
"""Application name recorded in every tracking row."""


class _DemoView(AsyncCoreView):
    """Minimal view over one table, used to exercise the shared helpers."""

    def __init__(self, datastore: AsyncSQLAlchemyDatastore, tracking_table: Table) -> None:
        super().__init__(datastore, tracking_table=tracking_table)
        self.view_metadata = MetaData()

    def build_metadata(self) -> None:
        """Declares the demo table on the view's own metadata."""
        Table("demo_rows", self.view_metadata, Column("name", String, primary_key=True))


@pytest.fixture
async def datastore(tmp_path: Path) -> AsyncIterator[AsyncSQLAlchemyDatastore]:
    """A file-backed SQLite datastore so the helpers share one engine."""
    store = AsyncSQLAlchemyDatastore(f"sqlite+aiosqlite:///{tmp_path / 'persistence.db'}")
    try:
        yield store
    finally:
        await store.close()


def _view(datastore: AsyncSQLAlchemyDatastore) -> _DemoView:
    view = _DemoView(datastore, datastore.create_tracking_table("demo_projection_tracking"))
    view.build_metadata()
    return view


def test_utc_now_is_timezone_aware() -> None:
    """Soft-delete timestamps are aware so both backends round-trip them."""
    assert utc_now().tzinfo is not None


async def test_create_table_builds_the_view_and_tracking_tables(
    datastore: AsyncSQLAlchemyDatastore,
) -> None:
    """The base class creates the view metadata and the datastore metadata."""
    view = _view(datastore)

    await view.create_table()

    rows = await view._fetch_all(select(view.view_metadata.tables["demo_rows"].c.name))
    assert rows == []


async def test_write_records_the_change_with_its_tracking_row(
    datastore: AsyncSQLAlchemyDatastore,
) -> None:
    """A write and its tracking row land in one transaction."""
    from eventsourcing.persistence import Tracking

    view = _view(datastore)
    await view.create_table()
    table = view.view_metadata.tables["demo_rows"]

    await view._write([table.insert().values(name="one")], Tracking(UPSTREAM, 1))

    assert await view._fetch_one(select(table.c.name)) == ("one",)
    assert await view.max_tracking_id(UPSTREAM) == 1


async def test_fetch_one_returns_none_for_no_row(datastore: AsyncSQLAlchemyDatastore) -> None:
    """An empty read answers ``None`` instead of raising."""
    view = _view(datastore)
    await view.create_table()
    table = view.view_metadata.tables["demo_rows"]

    assert await view._fetch_one(select(table.c.name)) is None


async def test_ensure_column_adds_a_missing_column_once(
    datastore: AsyncSQLAlchemyDatastore,
) -> None:
    """The migration helper is idempotent on SQLite and PostgreSQL alike."""
    view = _view(datastore)
    await view.create_table()

    async with datastore.transaction() as conn:
        await ensure_column(
            conn,
            datastore.dialect_name,
            "demo_rows",
            "note",
            "TEXT NOT NULL DEFAULT ''",
        )
        await ensure_column(
            conn,
            datastore.dialect_name,
            "demo_rows",
            "note",
            "TEXT NOT NULL DEFAULT ''",
        )

    async with datastore.connection() as conn:
        result = await conn.exec_driver_sql("PRAGMA table_info(demo_rows)")
        columns = {str(row._mapping["name"]) for row in result.fetchall()}
    assert "note" in columns


async def test_migrate_hook_runs_inside_create_table(
    datastore: AsyncSQLAlchemyDatastore,
) -> None:
    """A subclass can add a column while the tables are being created."""
    calls: list[str] = []

    class _Migrating(_DemoView):
        async def migrate(self, conn: object) -> None:
            calls.append("migrate")
            await ensure_column(
                conn,
                self.datastore.dialect_name,
                "demo_rows",
                "added",
                "TEXT NOT NULL DEFAULT ''",
            )

    view = _Migrating(datastore, datastore.create_tracking_table("demo_migration_tracking"))
    view.build_metadata()
    await view.create_table()

    assert calls == ["migrate"]
    async with datastore.connection() as conn:
        result = await conn.exec_driver_sql("PRAGMA table_info(demo_rows)")
        columns = {str(row._mapping["name"]) for row in result.fetchall()}
    assert "added" in columns
