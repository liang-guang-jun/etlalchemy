"""Integration tests for the async PostgreSQL source adapter.

These tests need a running PostgreSQL database. Point ``TEST_DATABASE_URL`` (or
``ETLALCHEMY_DSN``) at it, for example:

    docker compose -f docker/docker-compose.yml up -d --wait
    export TEST_DATABASE_URL=postgresql://etlalchemy:etlalchemy@localhost:55432/etlalchemy_test
"""

import os
from collections.abc import Iterator
from urllib.parse import urlparse
from uuid import uuid4

import psycopg
import pytest

from etlalchemy.ingestion.adapters.postgres import PostgresSourceFactory
from etlalchemy.ingestion.adapters.secrets_composite import CompositeSecretsResolver
from etlalchemy.ingestion.aggregates.connection import SourceConnection
from etlalchemy.ingestion.aggregates.import_run import ImportRun
from etlalchemy.ingestion.application import IngestionApplication
from etlalchemy.ingestion.ports.secrets import SecretValue
from tests.ingestion.support import (
    FakeCatalogView,
    FakeConnectionsView,
    RecordingCatalogApplication,
)

DSN = os.environ.get("TEST_DATABASE_URL") or os.environ.get("ETLALCHEMY_DSN")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DSN, reason="TEST_DATABASE_URL is not set"),
]

PARTS = urlparse(DSN or "")


@pytest.fixture
def schema() -> Iterator[str]:
    """Creates a temporary schema with tables and a view, then drops it."""
    name = f"ingestion_{uuid4().hex[:8]}"
    with psycopg.connect(DSN or "", autocommit=True) as conn:
        conn.execute(f'CREATE SCHEMA "{name}"')
        conn.execute(
            f'CREATE TABLE "{name}".orders ('
            "id bigint NOT NULL, "
            "amount numeric(10,2), "
            "tags text[], "
            "created_at timestamp with time zone)"
        )
        conn.execute(f'CREATE TABLE "{name}".customers (id bigint NOT NULL, name text)')
        conn.execute(
            f'CREATE VIEW "{name}".order_totals AS SELECT id, amount FROM "{name}".orders'
        )
        try:
            yield name
        finally:
            conn.execute(f'DROP SCHEMA "{name}" CASCADE')


def connection(**options: str) -> SourceConnection:
    """Returns a connection describing the test database."""
    database = PARTS.path.lstrip("/")
    endpoint = (
        f"{PARTS.hostname}:{PARTS.port}" if PARTS.port else (PARTS.hostname or "localhost")
    )
    return SourceConnection(
        name="warehouse-pg",
        kind="postgres",
        endpoint=endpoint,
        token=PARTS.password or "",
        default_catalog=database,
        options={"user": PARTS.username or "postgres", "database": database, **options},
    )


async def test_source_lists_the_schema(schema: str) -> None:
    """The source lists the database, schema, tables and formatted columns."""
    created = connection()
    source = await PostgresSourceFactory().build(created, SecretValue(created.token or ""))
    database = created.default_catalog or ""
    try:
        assert await source.list_catalogs() == [database]
        assert schema in await source.list_schemas(database)
        assert await source.list_tables(database, schema) == ["customers", "orders"]
        columns = {
            column.name: column.raw_type
            for column in await source.list_columns(database, schema, "orders")
        }
        assert columns["id"] == "bigint"
        assert columns["amount"] == "numeric(10,2)"
        assert columns["tags"] == "text[]"
        assert columns["created_at"] == "timestamp with time zone"

        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            await source._conn.execute(f'INSERT INTO "{schema}".orders (id) VALUES (1)')
    finally:
        await source.close()


async def test_source_can_include_views(schema: str) -> None:
    """Views are listed only when the connection enables them."""
    created = connection(include_views="true")
    source = await PostgresSourceFactory().build(created, SecretValue(created.token or ""))
    database = created.default_catalog or ""
    try:
        assert await source.list_tables(database, schema) == [
            "customers",
            "order_totals",
            "orders",
        ]
    finally:
        await source.close()


async def test_import_from_reads_the_postgres_schema(
    schema: str,
    app_env: dict[str, str],
) -> None:
    """The full ingestion chain imports the temporary schema."""
    catalog_view = FakeCatalogView()
    catalog = RecordingCatalogApplication(catalog_view, env=app_env)
    created = connection()
    async with catalog, IngestionApplication(
        catalog=catalog,
        catalog_view=catalog_view,
        connections_view=FakeConnectionsView(),
        factories={"postgres": PostgresSourceFactory()},
        secrets=CompositeSecretsResolver({}),
        env=app_env,
    ) as app:
        target_id = await catalog.create_catalog("target")
        connection_id = await app.create_connection(
            name=created.name,
            kind=created.kind,
            endpoint=created.endpoint,
            token=created.token,
            default_catalog=created.default_catalog,
            options=created.options,
        )

        run_id = await app.import_from(
            connection_id,
            target_id,
            source_catalog=created.default_catalog,
            include_tables={schema: ["orders"]},
            schema_mapping={schema: f"{schema}_target"},
        )

        run = await app.repository.get(run_id)
        assert isinstance(run, ImportRun)
        assert run.status == "succeeded"
        assert run.include_tables == {schema: ["orders"]}
        assert run.schema_mapping == {schema: f"{schema}_target"}
        mapped = f"{schema}_target"
        assert list((await catalog.get_catalog(target_id)).schemas) == [mapped]
        assert list((await catalog.get_schema(target_id, mapped)).tables) == ["orders"]
        table = await catalog.get_table(target_id, mapped, "orders")
        assert table.fields["id"].nullable is False
        assert str(table.fields["amount"].data_type) == "decimal(10,2)"
        assert str(table.fields["tags"].data_type) == "json"
        assert str(table.fields["created_at"].data_type) == "timestamp"
