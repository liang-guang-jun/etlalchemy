"""Integration tests for the PostgreSQL catalog read model.

These tests need a running PostgreSQL database. Point `TEST_DATABASE_URL` (or
`ETLALCHEMY_DSN`) at it, for example:

    docker compose -f docker/docker-compose.yml up -d --wait
    export TEST_DATABASE_URL=postgresql://etlalchemy:etlalchemy@localhost:55432/etlalchemy_test
"""

import os
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
from eventsourcing.persistence import Tracking

from etlalchemy._vendor.eventsourcing.asyncio.sqlalchemy import AsyncSQLAlchemyDatastore
from etlalchemy.catalog.aggregates.types import DataType
from etlalchemy.catalog.application import CatalogApplication
from etlalchemy.catalog.projection.projection import run_catalog_projection
from etlalchemy.catalog.projection.sqlalchemy import SQLAlchemyCatalogView
from tests.support import async_env, async_postgres_url

DSN = os.environ.get("TEST_DATABASE_URL") or os.environ.get("ETLALCHEMY_DSN")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DSN, reason="TEST_DATABASE_URL is not set"),
]

VIEW_TABLES = (
    "catalog_catalogs",
    "catalog_fields",
    "catalog_tables",
    "catalog_schemas",
    "catalog_projection_tracking",
)

UPSTREAM = "catalog-application"


async def drop_tables(datastore: AsyncSQLAlchemyDatastore, tables: tuple[str, ...]) -> None:
    """Drops the given tables so every test starts from an empty read model."""
    async with datastore.engine.begin() as conn:
        for table in tables:
            await conn.exec_driver_sql(f'DROP TABLE IF EXISTS "{table}" CASCADE')


@pytest.fixture
async def datastore() -> AsyncIterator[AsyncSQLAlchemyDatastore]:
    """Returns a datastore with the catalog view tables dropped."""
    store = AsyncSQLAlchemyDatastore(async_postgres_url(DSN or ""))
    await drop_tables(store, VIEW_TABLES)
    try:
        yield store
    finally:
        await store.close()


@pytest.fixture
async def view(datastore: AsyncSQLAlchemyDatastore) -> AsyncIterator[SQLAlchemyCatalogView]:
    """Returns an empty Postgres view."""
    catalog_view = SQLAlchemyCatalogView(
        datastore=datastore,
        tracking_table=datastore.create_tracking_table("catalog_projection_tracking"),
    )
    await catalog_view.create_table()
    yield catalog_view


async def test_create_table_is_idempotent(view: SQLAlchemyCatalogView) -> None:
    """Creating the view tables twice does not fail."""
    await view.create_table()
    await view.create_table()


async def test_register_schema_stores_the_row_and_tracks_the_event(
    view: SQLAlchemyCatalogView,
) -> None:
    """A registered schema is queryable by id and by name."""
    catalog_id = uuid4()
    schema_id = uuid4()
    await view.register_schema(schema_id, catalog_id, "sales", "Sales data", Tracking(UPSTREAM, 1))

    schema = await view.get_schema(schema_id)
    assert schema is not None
    assert schema.catalog_id == catalog_id
    assert schema.name == "sales"
    assert schema.description == "Sales data"
    assert await view.list_schemas(catalog_id) == [schema]
    assert await view.find_schema_id(catalog_id, "sales") == schema_id
    assert await view.find_schema_id(catalog_id, "warehouse") is None
    assert await view.max_tracking_id(UPSTREAM) == 1


async def run_catalog_writes(view: SQLAlchemyCatalogView) -> tuple[UUID, UUID, UUID]:
    """Registers one schema, table and field in the view."""
    catalog_id = uuid4()
    schema_id = uuid4()
    table_id = uuid4()
    await view.register_schema(schema_id, catalog_id, "sales", "Sales data", Tracking(UPSTREAM, 1))
    await view.register_table(table_id, schema_id, catalog_id, "orders", Tracking(UPSTREAM, 2))
    await view.add_field(table_id, "id", DataType.parse("integer"), False, Tracking(UPSTREAM, 3))
    await view.add_field(table_id, "note", DataType.parse("text"), True, Tracking(UPSTREAM, 4))
    return catalog_id, schema_id, table_id


async def test_unregister_schema_cascades_to_tables_and_fields(
    view: SQLAlchemyCatalogView,
) -> None:
    """Removing a schema removes its tables and their fields."""
    catalog_id, schema_id, table_id = await run_catalog_writes(view)

    await view.unregister_schema(catalog_id, "sales", Tracking(UPSTREAM, 5))

    assert await view.list_schemas(catalog_id) == []
    assert await view.list_tables(schema_id) == []
    assert await view.list_fields(table_id) == []


async def test_change_field_updates_only_non_none_values(view: SQLAlchemyCatalogView) -> None:
    """FieldTypeChanged/FieldNullabilityChanged only touch what they carry."""
    _, _, table_id = await run_catalog_writes(view)

    await view.change_field(table_id, "id", DataType.parse("bigint"), None, Tracking(UPSTREAM, 5))
    await view.change_field(table_id, "id", None, True, Tracking(UPSTREAM, 6))

    fields = await view.list_fields(table_id)
    field = next(row for row in fields if row.name == "id")
    assert field.data_type == DataType.parse("bigint")
    assert field.nullable is True


async def test_search_fields_matches_all_name_levels(view: SQLAlchemyCatalogView) -> None:
    """Search matches schema, table and field names across the read model."""
    catalog_id, schema_id, table_id = await run_catalog_writes(view)

    results = await view.search_fields("note")

    assert len(results) == 1
    result = results[0]
    assert result.catalog_id == catalog_id
    assert result.schema_id == schema_id
    assert result.schema_name == "sales"
    assert result.table_id == table_id
    assert result.table_name == "orders"
    assert result.field_name == "note"
    assert result.data_type == DataType.parse("text")
    assert result.nullable is True
    assert await view.search_fields("note", catalog_id=uuid4()) == []


async def test_projection_runner_fills_the_postgres_view(
    datastore: AsyncSQLAlchemyDatastore,
) -> None:
    """The asynchronous runner works against the Postgres event store."""
    env = async_env(async_postgres_url(DSN or ""))
    await drop_tables(
        datastore,
        (*VIEW_TABLES, "catalog_application_events", "catalogapplication_events"),
    )

    async with CatalogApplication(env=env) as application:
        catalog_id = await application.create_catalog("analytics")
        schema_id = await application.create_schema(catalog_id, "sales", "Sales data")
        table_id = await application.add_table(catalog_id, "sales", "orders")
        await application.add_field(catalog_id, "sales", "orders", "id", "integer", nullable=False)
        last = await application.recorder.max_notification_id()
    assert last is not None

    async with run_catalog_projection(env) as runner:
        await runner.wait(last, timeout=5.0)
        reader = runner.view

        assert await reader.find_schema_id(catalog_id, "sales") == schema_id
        assert await reader.find_table_id(schema_id, "orders") == table_id
        assert await reader.get_catalog(catalog_id) is not None
        assert [row.name for row in await reader.list_fields(table_id)] == ["id"]
        assert await reader.max_tracking_id("catalog_application") == last


async def test_register_catalog_stores_the_row_and_tracks_the_event(
    view: SQLAlchemyCatalogView,
) -> None:
    """A registered catalog is queryable by id and listed by name."""
    catalog_id = uuid4()
    await view.register_catalog(
        catalog_id,
        "analytics",
        "Analytics warehouse",
        Tracking(UPSTREAM, 1),
    )

    catalog = await view.get_catalog(catalog_id)
    assert catalog is not None
    assert (catalog.name, catalog.description) == ("analytics", "Analytics warehouse")
    assert await view.list_catalogs() == [catalog]
    assert await view.get_catalog(uuid4()) is None
    assert await view.max_tracking_id(UPSTREAM) == 1


async def test_register_catalog_is_idempotent(view: SQLAlchemyCatalogView) -> None:
    """Replaying Catalog.Started upserts instead of failing."""
    catalog_id = uuid4()
    await view.register_catalog(catalog_id, "analytics", "Analytics", Tracking(UPSTREAM, 1))
    await view.register_catalog(catalog_id, "analytics", "Analytics", Tracking(UPSTREAM, 2))

    catalog = await view.get_catalog(catalog_id)
    assert catalog is not None
    assert await view.list_catalogs() == [catalog]
    assert await view.max_tracking_id(UPSTREAM) == 2


async def test_list_catalogs_is_ordered_by_name(view: SQLAlchemyCatalogView) -> None:
    """Catalogs are returned in name order."""
    await view.register_catalog(uuid4(), "warehouse", "", Tracking(UPSTREAM, 1))
    await view.register_catalog(uuid4(), "analytics", "", Tracking(UPSTREAM, 2))

    assert [row.name for row in await view.list_catalogs()] == ["analytics", "warehouse"]


async def test_change_and_discard_commands_are_reflected(
    view: SQLAlchemyCatalogView,
) -> None:
    """Renames, discards and soft-delete filters work on PostgreSQL."""
    catalog_id, schema_id, table_id = uuid4(), uuid4(), uuid4()
    await view.register_catalog(catalog_id, "analytics", "", Tracking(UPSTREAM, 1))
    await view.register_schema(schema_id, catalog_id, "sales", "Sales data", Tracking(UPSTREAM, 2))
    await view.register_table(table_id, schema_id, catalog_id, "orders", Tracking(UPSTREAM, 3))
    await view.add_field(table_id, "id", DataType.parse("bigint"), False, Tracking(UPSTREAM, 4))

    await view.change_catalog(catalog_id, "warehouse", None, Tracking(UPSTREAM, 5))
    await view.change_schema(schema_id, "revenue", None, Tracking(UPSTREAM, 6))
    await view.change_table(table_id, "purchases", Tracking(UPSTREAM, 7))
    await view.rename_field(table_id, "id", "order_id", Tracking(UPSTREAM, 8))

    catalog = await view.get_catalog(catalog_id)
    assert catalog is not None
    assert catalog.name == "warehouse"
    assert await view.find_schema_id(catalog_id, "revenue") == schema_id
    assert await view.find_table_id(schema_id, "purchases") == table_id
    assert [row.name for row in await view.list_fields(table_id)] == ["order_id"]

    await view.discard_table(table_id, Tracking(UPSTREAM, 9))
    assert await view.list_tables(schema_id) == []
    assert await view.list_fields(table_id) == []

    await view.discard_schema(schema_id, Tracking(UPSTREAM, 10))
    assert await view.list_schemas(catalog_id) == []

    await view.discard_catalog(catalog_id, Tracking(UPSTREAM, 11))
    assert await view.get_catalog(catalog_id) is None
    assert await view.list_catalogs() == []
    assert await view.search_fields("order_id") == []
