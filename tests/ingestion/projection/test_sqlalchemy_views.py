"""Tests for the SQLAlchemy-backed ingestion views.

The same lifecycle runs against SQLite and PostgreSQL so both backends keep the
same observable behaviour.
"""

import os
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from eventsourcing.asyncio.sqlalchemy import AsyncSQLAlchemyDatastore
from eventsourcing.persistence import Tracking

from etlalchemy.ingestion.projection.sqlalchemy import SQLAlchemyIngestionView
from etlalchemy.ingestion.projection.view import IngestionView
from tests.support import async_postgres_url, sqlite_url

UPSTREAM = "ingestion-application"

DSN = os.environ.get("TEST_DATABASE_URL") or os.environ.get("ETLALCHEMY_DSN")

VIEW_TABLES = (
    "ingestion_connections",
    "ingestion_import_runs",
    "ingestion_projection_tracking",
)


async def run_lifecycle(view: IngestionView) -> None:
    """Runs the full ingestion lifecycle against a await view."""
    connection_id = uuid4()
    second_id = uuid4()
    run_id = uuid4()
    catalog_id = uuid4()

    await view.register_connection(
        connection_id,
        "warehouse",
        "databricks",
        "https://example.test",
        "env:DBX_TOKEN",
        False,
        "main",
        {"warehouse_id": "abc"},
        Tracking(UPSTREAM, 1),
    )
    await view.register_connection(
        second_id,
        "analytics",
        "databricks",
        "https://analytics.test",
        None,
        True,
        None,
        {},
        Tracking(UPSTREAM, 2),
    )

    assert [row.name for row in await view.list_connections()] == ["analytics", "warehouse"]
    assert await view.find_connection_by_name("warehouse") is not None
    assert await view.find_connection_by_name("missing") is None

    await view.change_connection(connection_id, "renamed", None, None, {"warehouse_id": "xyz"}, Tracking(UPSTREAM, 3))
    changed = await view.get_connection(connection_id)
    assert changed is not None
    assert changed.name == "renamed"
    assert changed.options == {"warehouse_id": "xyz"}
    assert changed.endpoint == "https://example.test"

    await view.rotate_credential(connection_id, None, True, Tracking(UPSTREAM, 4))
    rotated = await view.get_connection(connection_id)
    assert rotated is not None
    assert rotated.credential_ref is None
    assert rotated.has_inline_credential is True

    await view.register_import_run(
        run_id,
        connection_id,
        catalog_id,
        "src",
        ["sales"],
        {},
        {},
        Tracking(UPSTREAM, 5),
    )
    pending = await view.get_import_run(run_id)
    assert pending is not None
    assert pending.status == "pending"
    assert pending.include_schemas == ["sales"]

    await view.finish_import_run(
        run_id,
        "succeeded",
        1,
        2,
        3,
        None,
        Tracking(UPSTREAM, 6),
    )
    finished = await view.get_import_run(run_id)
    assert finished is not None
    assert finished.status == "succeeded"
    assert (finished.schema_count, finished.table_count, finished.field_count) == (1, 2, 3)

    await view.discard_connection(connection_id, Tracking(UPSTREAM, 7))
    assert await view.get_connection(connection_id) is None
    assert await view.find_connection_by_name("renamed") is None
    assert [row.name for row in await view.list_connections()] == ["analytics"]

    replacement_id = uuid4()
    await view.register_connection(
        replacement_id,
        "renamed",
        "databricks",
        "https://example.test",
        "env:DBX_TOKEN",
        False,
        None,
        {},
        Tracking(UPSTREAM, 8),
    )
    assert await view.find_connection_by_name("renamed") is not None
    assert await view.max_tracking_id(UPSTREAM) == 8


async def run_replayed_commands(view: IngestionView) -> None:
    """Replays the same commands and checks the final state is unchanged."""
    connection_id = uuid4()
    run_id = uuid4()

    await view.register_connection(
        connection_id,
        "warehouse",
        "databricks",
        "https://example.test",
        "env:DBX_TOKEN",
        False,
        None,
        {},
        Tracking(UPSTREAM, 1),
    )
    await view.register_connection(
        connection_id,
        "warehouse",
        "databricks",
        "https://example.test",
        "env:DBX_TOKEN",
        False,
        None,
        {},
        Tracking(UPSTREAM, 2),
    )
    await view.register_import_run(
        run_id,
        connection_id,
        uuid4(),
        "src",
        [],
        {},
        {},
        Tracking(UPSTREAM, 3),
    )
    await view.register_import_run(
        run_id,
        connection_id,
        uuid4(),
        "src",
        [],
        {},
        {},
        Tracking(UPSTREAM, 4),
    )

    assert [row.name for row in await view.list_connections()] == ["warehouse"]
    assert len(await view.list_import_runs()) == 1
    assert await view.max_tracking_id(UPSTREAM) == 4


async def test_sqlite_view_runs_the_lifecycle(tmp_path: Path) -> None:
    """The SQLite view supports the full ingestion lifecycle."""
    datastore = AsyncSQLAlchemyDatastore(sqlite_url(tmp_path / "await view.db"))
    sut = build_view(datastore)
    try:
        await sut.create_table()
        await sut.create_table()
        await run_lifecycle(sut)
    finally:
        await datastore.close()


async def test_sqlite_view_is_idempotent_for_replayed_commands(tmp_path: Path) -> None:
    """Re-registering a connection or run upserts instead of failing."""
    datastore = AsyncSQLAlchemyDatastore(sqlite_url(tmp_path / "await view.db"))
    sut = build_view(datastore)
    try:
        await sut.create_table()
        await run_replayed_commands(sut)
    finally:
        await datastore.close()


def build_view(datastore: AsyncSQLAlchemyDatastore) -> SQLAlchemyIngestionView:
    """Returns an ingestion view that records tracking in its default table."""
    return SQLAlchemyIngestionView(
        datastore=datastore,
        tracking_table=datastore.create_tracking_table("ingestion_projection_tracking"),
    )


async def build_postgres_view() -> tuple[AsyncSQLAlchemyDatastore, SQLAlchemyIngestionView]:
    """Returns a Postgres datastore with the ingestion view tables dropped."""
    datastore = AsyncSQLAlchemyDatastore(async_postgres_url(DSN or ""))
    async with datastore.engine.begin() as conn:
        for table in VIEW_TABLES:
            await conn.exec_driver_sql(f'DROP TABLE IF EXISTS "{table}" CASCADE')
    return datastore, build_view(datastore)


@pytest.mark.integration
@pytest.mark.skipif(not DSN, reason="TEST_DATABASE_URL is not set")
async def test_postgres_view_runs_the_lifecycle() -> None:
    """The Postgres view supports the full ingestion lifecycle."""
    datastore, sut = await build_postgres_view()
    try:
        await sut.create_table()
        await sut.create_table()
        await run_lifecycle(sut)
    finally:
        await datastore.close()


@pytest.mark.integration
@pytest.mark.skipif(not DSN, reason="TEST_DATABASE_URL is not set")
async def test_postgres_view_is_idempotent_for_replayed_commands() -> None:
    """Re-registering a connection or run upserts instead of failing."""
    datastore, sut = await build_postgres_view()
    try:
        await sut.create_table()
        await run_replayed_commands(sut)
    finally:
        await datastore.close()
