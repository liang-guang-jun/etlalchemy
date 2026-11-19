"""Tests for the async SQLAlchemy catalog view.

The view keeps the same observable behaviour as before the refactor: the tests
below run the full catalog lifecycle on both backends, check partial field updates,
and check that replayed commands (upserts) are idempotent.
"""

import os
from pathlib import Path
from uuid import uuid4

import pytest
from etlalchemy.catalog.aggregates.types import DataType
from etlalchemy.catalog.projection.sqlalchemy import SQLAlchemyCatalogView
from etlalchemy.catalog.projection.view import CatalogView
from eventsourcing.asyncio.sqlalchemy import AsyncSQLAlchemyDatastore
from eventsourcing.persistence import Tracking

from tests.support import async_postgres_url, sqlite_url

UPSTREAM = "catalog-application"

DSN = os.environ.get("TEST_DATABASE_URL") or os.environ.get("ETLALCHEMY_DSN")

VIEW_TABLES = (
    "catalog_catalogs",
    "catalog_fields",
    "catalog_tables",
    "catalog_schemas",
    "catalog_projection_tracking",
)


async def run_lifecycle(view: CatalogView) -> None:
    """Runs the full catalog lifecycle against a view."""
    catalog_id, schema_id, table_id = uuid4(), uuid4(), uuid4()

    await view.register_catalog(
        catalog_id, "analytics", "Analytics warehouse", Tracking(UPSTREAM, 1)
    )
    await view.register_schema(schema_id, catalog_id, "sales", "Sales data", Tracking(UPSTREAM, 2))
    await view.register_table(table_id, schema_id, catalog_id, "orders", Tracking(UPSTREAM, 3))
    await view.add_field(table_id, "id", DataType.parse("integer"), False, Tracking(UPSTREAM, 4))
    await view.add_field(table_id, "note", DataType.parse("text"), True, Tracking(UPSTREAM, 5))

    await view.change_field(
        table_id, "note", DataType.parse("varchar"), None, Tracking(UPSTREAM, 6)
    )
    fields = await view.list_fields(table_id)
    note = next(row for row in fields if row.name == "note")
    assert (str(note.data_type), note.nullable) == ("varchar", True)

    await view.change_field(table_id, "note", None, False, Tracking(UPSTREAM, 7))
    fields = await view.list_fields(table_id)
    note = next(row for row in fields if row.name == "note")
    assert (str(note.data_type), note.nullable) == ("varchar", False)

    catalog = await view.get_catalog(catalog_id)
    assert catalog is not None
    assert (catalog.name, catalog.description) == ("analytics", "Analytics warehouse")
    assert [row.catalog_id for row in await view.list_catalogs()] == [catalog_id]

    assert await view.find_schema_id(catalog_id, "sales") == schema_id
    assert await view.find_table_id(schema_id, "orders") == table_id
    assert [row.field_name for row in await view.search_fields("note")] == ["note"]
    assert await view.search_fields("note", catalog_id=uuid4()) == []

    assert [(row.kind, row.path) for row in await view.search_objects("sales")] == [
        ("schema", "analytics / sales")
    ]
    assert [(row.kind, row.name) for row in await view.search_objects("order")] == [
        ("table", "orders")
    ]
    assert [(row.kind, row.name) for row in await view.search_objects("analytics")] == [
        ("catalog", "analytics")
    ]
    assert await view.search_objects("order", catalog_id=uuid4()) == []

    await view.remove_field(table_id, "note", Tracking(UPSTREAM, 8))
    assert [row.name for row in await view.list_fields(table_id)] == ["id"]

    await view.change_table(table_id, "purchases", Tracking(UPSTREAM, 9), description="Purchases")
    assert await view.find_table_id(schema_id, "purchases") == table_id
    changed_table = await view.get_table(table_id)
    assert changed_table is not None
    assert (changed_table.name, changed_table.description) == ("purchases", "Purchases")
    await view.rename_field(table_id, "id", "order_id", Tracking(UPSTREAM, 10))
    assert [row.name for row in await view.list_fields(table_id)] == ["order_id"]

    await view.change_schema(schema_id, "revenue", "Revenue data", Tracking(UPSTREAM, 11))
    assert await view.find_schema_id(catalog_id, "revenue") == schema_id
    assert [row.description for row in await view.list_schemas(catalog_id)] == ["Revenue data"]

    await view.change_catalog(catalog_id, "warehouse", None, Tracking(UPSTREAM, 12))
    changed = await view.get_catalog(catalog_id)
    assert changed is not None
    assert changed.name == "warehouse"

    await view.discard_table(table_id, Tracking(UPSTREAM, 13))
    assert await view.list_tables(schema_id) == []
    assert await view.list_fields(table_id) == []
    assert await view.search_fields("order_id") == []
    assert await view.search_objects("order_id") == []

    await view.unregister_schema(catalog_id, "revenue", Tracking(UPSTREAM, 14))
    assert await view.list_schemas(catalog_id) == []
    assert await view.max_tracking_id(UPSTREAM) == 14

    await view.discard_catalog(catalog_id, Tracking(UPSTREAM, 15))
    assert await view.get_catalog(catalog_id) is None
    assert await view.list_catalogs() == []
    assert await view.max_tracking_id(UPSTREAM) == 15


async def run_replayed_commands(view: CatalogView) -> None:
    """Replays the same commands and checks the final state is unchanged."""
    catalog_id, schema_id, table_id = uuid4(), uuid4(), uuid4()

    await view.register_catalog(catalog_id, "analytics", "Analytics", Tracking(UPSTREAM, 1))
    await view.register_catalog(catalog_id, "analytics", "Analytics", Tracking(UPSTREAM, 2))
    await view.register_schema(schema_id, catalog_id, "sales", "Sales data", Tracking(UPSTREAM, 3))
    await view.register_schema(schema_id, catalog_id, "sales", "Sales data", Tracking(UPSTREAM, 4))
    await view.register_table(table_id, schema_id, catalog_id, "orders", Tracking(UPSTREAM, 5))
    await view.register_table(table_id, schema_id, catalog_id, "orders", Tracking(UPSTREAM, 6))
    await view.add_field(table_id, "id", DataType.parse("integer"), False, Tracking(UPSTREAM, 7))
    await view.add_field(table_id, "id", DataType.parse("integer"), False, Tracking(UPSTREAM, 8))

    assert await view.max_tracking_id(UPSTREAM) == 8
    assert [row.name for row in await view.list_catalogs()] == ["analytics"]
    assert [row.name for row in await view.list_schemas(catalog_id)] == ["sales"]
    assert [row.name for row in await view.list_tables(schema_id)] == ["orders"]
    fields = [
        (row.name, str(row.data_type), row.nullable) for row in await view.list_fields(table_id)
    ]
    assert fields == [("id", "integer", False)]

    await view.rename_field(table_id, "id", "id", Tracking(UPSTREAM, 9))
    await view.rename_field(table_id, "missing", "other", Tracking(UPSTREAM, 10))
    assert [row.name for row in await view.list_fields(table_id)] == ["id"]


def build_view(datastore: AsyncSQLAlchemyDatastore) -> SQLAlchemyCatalogView:
    """Returns a catalog view that records tracking in its default table."""
    return SQLAlchemyCatalogView(
        datastore=datastore,
        tracking_table=datastore.create_tracking_table("catalog_projection_tracking"),
    )


async def test_sqlite_view_runs_the_lifecycle(tmp_path: Path) -> None:
    """The SQLite view supports the full catalog lifecycle."""
    datastore = AsyncSQLAlchemyDatastore(sqlite_url(tmp_path / "view.db"))
    try:
        view = build_view(datastore)
        await view.create_table()
        await view.create_table()
        await run_lifecycle(view)
    finally:
        await datastore.close()


async def test_sqlite_view_is_idempotent_for_replayed_commands(tmp_path: Path) -> None:
    """Re-registering a schema, table or field upserts instead of failing."""
    datastore = AsyncSQLAlchemyDatastore(sqlite_url(tmp_path / "view.db"))
    try:
        view = build_view(datastore)
        await view.create_table()
        await run_replayed_commands(view)
    finally:
        await datastore.close()


async def test_sqlite_view_searches_every_level(tmp_path: Path) -> None:
    """A term resolves to catalogs, schemas, tables and fields with their paths."""
    datastore = AsyncSQLAlchemyDatastore(sqlite_url(tmp_path / "view.db"))
    try:
        view = build_view(datastore)
        await view.create_table()
        catalog_id, schema_id, table_id = uuid4(), uuid4(), uuid4()
        await view.register_catalog(catalog_id, "test", "", Tracking(UPSTREAM, 1))
        await view.register_schema(schema_id, catalog_id, "vault_roles", "", Tracking(UPSTREAM, 2))
        await view.register_table(table_id, schema_id, catalog_id, "policy", Tracking(UPSTREAM, 3))
        await view.add_field(
            table_id,
            "POLICY_NO",
            DataType.parse("varchar(32)"),
            False,
            Tracking(UPSTREAM, 4),
        )

        hits = await view.search_objects("policy")
        assert [(row.kind, row.path) for row in hits] == [
            ("table", "test / vault_roles / policy"),
            ("field", "test / vault_roles / policy / POLICY_NO"),
        ]
        assert hits[1].target_id == table_id
        assert hits[1].field_name == "POLICY_NO"
        assert hits[1].data_type == "varchar(32)"

        assert [(row.kind, row.name) for row in await view.search_objects("vault")] == [
            ("schema", "vault_roles")
        ]
        assert [(row.kind, row.name) for row in await view.search_objects("test")] == [
            ("catalog", "test")
        ]
        assert [(row.kind, row.path) for row in await view.search_objects("POLICY")] == [
            ("table", "test / vault_roles / policy"),
            ("field", "test / vault_roles / policy / POLICY_NO"),
        ]
    finally:
        await datastore.close()


async def build_postgres_view() -> tuple[AsyncSQLAlchemyDatastore, SQLAlchemyCatalogView]:
    """Returns a Postgres datastore whose catalog view tables were dropped."""
    datastore = AsyncSQLAlchemyDatastore(async_postgres_url(DSN or ""))
    async with datastore.engine.begin() as conn:
        for table in VIEW_TABLES:
            await conn.exec_driver_sql(f'DROP TABLE IF EXISTS "{table}" CASCADE')
    return datastore, build_view(datastore)


@pytest.mark.integration
@pytest.mark.skipif(not DSN, reason="TEST_DATABASE_URL is not set")
async def test_postgres_view_runs_the_lifecycle() -> None:
    """The Postgres view supports the full catalog lifecycle."""
    datastore, view = await build_postgres_view()
    try:
        await view.create_table()
        await view.create_table()
        await run_lifecycle(view)
    finally:
        await datastore.close()


@pytest.mark.integration
@pytest.mark.skipif(not DSN, reason="TEST_DATABASE_URL is not set")
async def test_postgres_view_is_idempotent_for_replayed_commands() -> None:
    """Re-registering a schema, table or field upserts instead of failing."""
    datastore, view = await build_postgres_view()
    try:
        await view.create_table()
        await run_replayed_commands(view)
    finally:
        await datastore.close()
