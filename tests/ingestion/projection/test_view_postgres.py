"""Integration tests for the Postgres ingestion read model.

These tests need a running PostgreSQL database. Point `TEST_DATABASE_URL` (or
`ETLALCHEMY_DSN`) at it, for example:

    docker compose -f docker/docker-compose.yml up -d --wait
    export TEST_DATABASE_URL=postgresql://etlalchemy:etlalchemy@localhost:55432/etlalchemy_test
"""

import os
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from eventsourcing.persistence import Tracking

from etlalchemy._vendor.eventsourcing.asyncio.sqlalchemy import AsyncSQLAlchemyDatastore
from etlalchemy.ingestion.aggregates.connection import SourceConnection
from etlalchemy.ingestion.aggregates.import_run import ImportRun
from etlalchemy.ingestion.projection.projection import (
    IngestionEventApplication,
    run_ingestion_projection,
)
from etlalchemy.ingestion.projection.sqlalchemy import SQLAlchemyIngestionView
from tests.support import async_env, async_postgres_url

DSN = os.environ.get("TEST_DATABASE_URL") or os.environ.get("ETLALCHEMY_DSN")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DSN, reason="TEST_DATABASE_URL is not set"),
]

VIEW_TABLES = (
    "ingestion_connections",
    "ingestion_import_runs",
    "ingestion_projection_tracking",
    "ingestion_application_events",
)

UPSTREAM = "ingestion_application"


def tracking_for(notification_id: int) -> Tracking:
    """Returns a tracking record for the ingestion application."""
    return Tracking(UPSTREAM, notification_id)


def build_view(datastore: AsyncSQLAlchemyDatastore) -> SQLAlchemyIngestionView:
    """Returns an ingestion view that records tracking in its default table."""
    return SQLAlchemyIngestionView(
        datastore=datastore,
        tracking_table=datastore.create_tracking_table("ingestion_projection_tracking"),
    )


async def drop_tables(datastore: AsyncSQLAlchemyDatastore, tables: tuple[str, ...]) -> None:
    """Drops the given tables so every test starts from an empty read model."""
    async with datastore.engine.begin() as conn:
        for table in tables:
            await conn.exec_driver_sql(f'DROP TABLE IF EXISTS "{table}" CASCADE')


@pytest.fixture
async def datastore() -> AsyncIterator[AsyncSQLAlchemyDatastore]:
    """Returns a datastore with the ingestion view tables dropped."""
    store = AsyncSQLAlchemyDatastore(async_postgres_url(DSN or ""))
    await drop_tables(store, VIEW_TABLES)
    try:
        yield store
    finally:
        await store.close()


@pytest.fixture
async def view(datastore: AsyncSQLAlchemyDatastore) -> AsyncIterator[SQLAlchemyIngestionView]:
    """Returns an empty Postgres ingestion view."""
    ingestion_view = build_view(datastore)
    await ingestion_view.create_table()
    yield ingestion_view


async def test_create_table_is_idempotent(view: SQLAlchemyIngestionView) -> None:
    """Creating the view tables twice does not fail."""
    await view.create_table()
    await view.create_table()


async def test_create_table_migrates_an_old_import_runs_table(
    datastore: AsyncSQLAlchemyDatastore,
) -> None:
    """An existing import run table gets the new columns added."""
    async with datastore.engine.begin() as conn:
        await conn.exec_driver_sql('DROP TABLE IF EXISTS "ingestion_import_runs" CASCADE')
        await conn.exec_driver_sql(
            'CREATE TABLE "ingestion_import_runs" ('
            "run_id uuid PRIMARY KEY, "
            "connection_id uuid NOT NULL, "
            "target_catalog_id uuid NOT NULL, "
            "source_catalog text, "
            "include_schemas text NOT NULL DEFAULT '[]', "
            "status text NOT NULL, "
            "schema_count integer NOT NULL, "
            "table_count integer NOT NULL, "
            "field_count integer NOT NULL, "
            "error text, "
            "created_at timestamptz NOT NULL)"
        )
    ingestion_view = build_view(datastore)

    await ingestion_view.create_table()

    async with datastore.engine.connect() as conn:
        result = await conn.exec_driver_sql(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'ingestion_import_runs'"
        )
        columns = {str(row._mapping["column_name"]) for row in result.fetchall()}
    assert {"include_tables", "schema_mapping"} <= columns


async def test_connection_and_run_rows_round_trip(view: SQLAlchemyIngestionView) -> None:
    """Connections and runs survive the Postgres round trip."""
    connection_id = uuid4()
    await view.register_connection(
        connection_id,
        "warehouse",
        "databricks",
        "https://example.test",
        "env:DBX_TOKEN",
        False,
        "main",
        {"warehouse_id": "abc"},
        tracking_for(1),
    )

    connection = await view.get_connection(connection_id)
    assert connection is not None
    assert connection.name == "warehouse"
    assert connection.options == {"warehouse_id": "abc"}
    assert await view.find_connection_by_name("warehouse") is not None

    run_id = uuid4()
    await view.register_import_run(
        run_id,
        connection_id,
        uuid4(),
        "src",
        ["sales"],
        {"sales": ["orders"]},
        {"sales": "sales_raw"},
        tracking_for(2),
    )
    await view.finish_import_run(run_id, "succeeded", 1, 2, 3, None, tracking_for(3))

    run = await view.get_import_run(run_id)
    assert run is not None
    assert run.status == "succeeded"
    assert run.include_schemas == ["sales"]
    assert run.include_tables == {"sales": ["orders"]}
    assert run.schema_mapping == {"sales": "sales_raw"}
    assert (run.schema_count, run.table_count, run.field_count) == (1, 2, 3)


async def test_projection_runner_fills_the_postgres_view(
    datastore: AsyncSQLAlchemyDatastore,
) -> None:
    """The asynchronous runner works against the Postgres event store."""
    env = async_env(async_postgres_url(DSN or ""))
    await drop_tables(datastore, VIEW_TABLES)

    async with IngestionEventApplication(env=env) as app:
        connection = SourceConnection(
            name="warehouse",
            kind="databricks",
            endpoint="https://example.test",
            token="s3cr3t",
            options={"warehouse_id": "abc"},
        )
        await app.save(connection)
        run = ImportRun(
            connection_id=connection.id,
            target_catalog_id=uuid4(),
            source_catalog="src",
            include_schemas=["sales"],
        )
        await app.save(run)
        run.succeed(1, 2, 3)
        await app.save(run)
        last = await app.recorder.max_notification_id()
    assert last is not None

    async with run_ingestion_projection(env) as runner:
        await runner.wait(last, timeout=5.0)
        reader = runner.view

        row = await reader.get_connection(connection.id)
        assert row is not None
        assert row.name == "warehouse"
        assert row.has_inline_credential is True
        assert row.credential_ref is None
        assert row.options == {"warehouse_id": "abc"}
        assert await reader.find_connection_by_name("warehouse") is not None

        run_row = await reader.get_import_run(run.id)
        assert run_row is not None
        assert run_row.status == "succeeded"
        assert run_row.include_schemas == ["sales"]
        assert (run_row.schema_count, run_row.table_count, run_row.field_count) == (1, 2, 3)
        assert await reader.max_tracking_id("ingestion_application") == last
