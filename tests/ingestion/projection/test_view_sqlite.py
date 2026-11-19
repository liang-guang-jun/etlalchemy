"""Tests for the SQLite ingestion read model."""

from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from etlalchemy.ingestion.projection.sqlalchemy import SQLAlchemyIngestionView
from etlalchemy.ingestion.projection.view import ConnectionRow, ImportRunRow
from eventsourcing.asyncio.sqlalchemy import AsyncSQLAlchemyDatastore
from eventsourcing.persistence import IntegrityError, Tracking

from tests.support import sqlite_url

UPSTREAM = "ingestion-application"


def build_view(datastore: AsyncSQLAlchemyDatastore) -> SQLAlchemyIngestionView:
    """Returns an ingestion view that records tracking in its default table."""
    return SQLAlchemyIngestionView(
        datastore=datastore,
        tracking_table=datastore.create_tracking_table("ingestion_projection_tracking"),
    )


@pytest.fixture
async def view(tmp_path: Path) -> AsyncIterator[SQLAlchemyIngestionView]:
    """Returns an empty view backed by a temporary database file."""
    datastore = AsyncSQLAlchemyDatastore(sqlite_url(tmp_path / "view.db"))
    try:
        catalog_view = build_view(datastore)
        await catalog_view.create_table()
        yield catalog_view
    finally:
        await datastore.close()


async def register_connection(
    view: SQLAlchemyIngestionView,
    name: str,
    tracking_id: int,
    **overrides: object,
) -> UUID:
    """Registers a connection in the view and returns its id."""
    connection_id = uuid4()
    await view.register_connection(
        connection_id,
        name,
        str(overrides.get("kind", "databricks")),
        str(overrides.get("endpoint", "https://example.test")),
        overrides.get("credential_ref", "env:DBX_TOKEN"),  # type: ignore[arg-type]
        bool(overrides.get("has_inline_credential", False)),
        overrides.get("default_catalog"),  # type: ignore[arg-type]
        overrides.get("options", {}),  # type: ignore[arg-type]
        Tracking(UPSTREAM, tracking_id),
    )
    return connection_id


async def test_create_table_is_idempotent(view: SQLAlchemyIngestionView) -> None:
    """Creating the view tables twice does not fail."""
    await view.create_table()
    await view.create_table()


async def test_create_table_migrates_an_old_import_runs_table(tmp_path: Path) -> None:
    """An existing import run table gets the new columns added."""
    datastore = AsyncSQLAlchemyDatastore(sqlite_url(tmp_path / "view.db"))
    try:
        async with datastore.engine.begin() as conn:
            await conn.exec_driver_sql(
                "CREATE TABLE ingestion_import_runs ("
                "run_id TEXT PRIMARY KEY, "
                "connection_id TEXT NOT NULL, "
                "target_catalog_id TEXT NOT NULL, "
                "source_catalog TEXT, "
                "include_schemas TEXT NOT NULL DEFAULT '[]', "
                "status TEXT NOT NULL, "
                "schema_count INTEGER NOT NULL, "
                "table_count INTEGER NOT NULL, "
                "field_count INTEGER NOT NULL, "
                "error TEXT, "
                "created_at TEXT NOT NULL)"
            )
        view = build_view(datastore)
        await view.create_table()
        async with datastore.engine.connect() as conn:
            result = await conn.exec_driver_sql("PRAGMA table_info(ingestion_import_runs)")
            columns = {str(row._mapping["name"]) for row in result.fetchall()}
        assert {"include_tables", "schema_mapping"} <= columns
    finally:
        await datastore.close()


async def test_register_connection_stores_the_row_and_tracks_the_event(
    view: SQLAlchemyIngestionView,
) -> None:
    """A registered connection is queryable by id and by name."""
    connection_id = await register_connection(
        view,
        "warehouse",
        tracking_id=1,
        kind="databricks",
        default_catalog="main",
        options={"warehouse_id": "abc"},
    )

    expected = ConnectionRow(
        connection_id=connection_id,
        name="warehouse",
        kind="databricks",
        endpoint="https://example.test",
        credential_ref="env:DBX_TOKEN",
        has_inline_credential=False,
        default_catalog="main",
        options={"warehouse_id": "abc"},
    )
    assert await view.get_connection(connection_id) == expected
    assert await view.find_connection_by_name("warehouse") == expected
    assert await view.find_connection_by_name("missing") is None
    assert await view.list_connections() == [expected]
    assert await view.get_connection(uuid4()) is None
    assert await view.max_tracking_id(UPSTREAM) == 1


async def test_register_connection_is_idempotent(view: SQLAlchemyIngestionView) -> None:
    """Replaying SourceConnection.Started upserts instead of failing."""
    connection_id = uuid4()
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

    assert len(await view.list_connections()) == 1
    assert await view.max_tracking_id(UPSTREAM) == 2


async def test_list_connections_is_ordered_by_name(view: SQLAlchemyIngestionView) -> None:
    """Connections are returned in name order."""
    await register_connection(view, "warehouse", tracking_id=1)
    await register_connection(view, "analytics", tracking_id=2)

    assert [row.name for row in await view.list_connections()] == ["analytics", "warehouse"]


async def test_list_connections_filters_by_kind_and_pages(
    view: SQLAlchemyIngestionView,
) -> None:
    """The read tool can filter by kind and page the result."""
    await register_connection(view, "warehouse", tracking_id=1, kind="postgres")
    await register_connection(view, "analytics", tracking_id=2, kind="databricks")
    await register_connection(view, "lake", tracking_id=3, kind="postgres")

    assert [row.name for row in await view.list_connections(kind="postgres")] == [
        "lake",
        "warehouse",
    ]
    assert [row.name for row in await view.list_connections(limit=1)] == ["analytics"]
    assert [row.name for row in await view.list_connections(limit=1, offset=1)] == ["lake"]


async def test_change_connection_updates_only_non_none_values(
    view: SQLAlchemyIngestionView,
) -> None:
    """SourceConnection.Changed only touches the fields it carries."""
    connection_id = await register_connection(
        view,
        "warehouse",
        tracking_id=1,
        default_catalog="main",
        options={"warehouse_id": "abc"},
    )

    await view.change_connection(
        connection_id,
        "renamed",
        None,
        None,
        None,
        Tracking(UPSTREAM, 2),
    )

    row = await view.get_connection(connection_id)
    assert row is not None
    assert row.name == "renamed"
    assert row.endpoint == "https://example.test"
    assert row.default_catalog == "main"
    assert row.options == {"warehouse_id": "abc"}


async def test_rotate_credential_updates_the_pointer(view: SQLAlchemyIngestionView) -> None:
    """Rotation switches between an external reference and an inline token."""
    connection_id = await register_connection(view, "warehouse", tracking_id=1)

    await view.rotate_credential(connection_id, None, True, Tracking(UPSTREAM, 2))

    row = await view.get_connection(connection_id)
    assert row is not None
    assert row.credential_ref is None
    assert row.has_inline_credential is True


async def test_discard_connection_hides_it_and_allows_name_reuse(
    view: SQLAlchemyIngestionView,
) -> None:
    """A discarded connection disappears and its name can be registered again."""
    connection_id = await register_connection(view, "warehouse", tracking_id=1)

    await view.discard_connection(connection_id, Tracking(UPSTREAM, 2))

    assert await view.get_connection(connection_id) is None
    assert await view.find_connection_by_name("warehouse") is None
    assert await view.list_connections() == []

    replacement_id = await register_connection(view, "warehouse", tracking_id=3)
    replacement = await view.find_connection_by_name("warehouse")
    assert replacement is not None
    assert replacement.connection_id == replacement_id


async def test_tracking_conflict_rolls_back_the_view_change(
    view: SQLAlchemyIngestionView,
) -> None:
    """A duplicated notification id aborts the whole transaction."""
    connection_id = await register_connection(view, "warehouse", tracking_id=2)

    with pytest.raises(IntegrityError):
        await view.register_connection(
            uuid4(),
            "other",
            "databricks",
            "https://example.test",
            None,
            True,
            None,
            {},
            Tracking(UPSTREAM, 2),
        )

    row = await view.get_connection(connection_id)
    assert row is not None
    assert [candidate.name for candidate in await view.list_connections()] == ["warehouse"]
    assert await view.max_tracking_id(UPSTREAM) == 2


async def test_import_run_lifecycle(view: SQLAlchemyIngestionView) -> None:
    """A run is created as pending and finalised with its counters."""
    run_id = uuid4()
    connection_id = uuid4()
    catalog_id = uuid4()

    await view.register_import_run(
        run_id,
        connection_id,
        catalog_id,
        "src",
        ["sales"],
        {"sales": ["orders"]},
        {"sales": "sales_raw"},
        Tracking(UPSTREAM, 1),
    )

    pending = await view.get_import_run(run_id)
    assert pending is not None
    assert pending.created_at is not None
    assert pending == ImportRunRow(
        run_id=run_id,
        connection_id=connection_id,
        target_catalog_id=catalog_id,
        source_catalog="src",
        include_schemas=["sales"],
        include_tables={"sales": ["orders"]},
        schema_mapping={"sales": "sales_raw"},
        status="pending",
        schema_count=0,
        table_count=0,
        field_count=0,
        error=None,
        created_at=pending.created_at,
    )

    await view.finish_import_run(
        run_id,
        "succeeded",
        1,
        2,
        3,
        None,
        Tracking(UPSTREAM, 2),
    )

    finished = await view.get_import_run(run_id)
    assert finished is not None
    assert finished.status == "succeeded"
    assert (finished.schema_count, finished.table_count, finished.field_count) == (1, 2, 3)
    assert finished.error is None


async def test_failed_import_run_records_the_error(view: SQLAlchemyIngestionView) -> None:
    """A failed run stores its error message."""
    run_id = uuid4()
    await view.register_import_run(
        run_id,
        uuid4(),
        uuid4(),
        None,
        [],
        {},
        {},
        Tracking(UPSTREAM, 1),
    )

    await view.finish_import_run(
        run_id,
        "failed",
        1,
        0,
        0,
        "boom",
        Tracking(UPSTREAM, 2),
    )

    row = await view.get_import_run(run_id)
    assert row is not None
    assert row.status == "failed"
    assert row.error == "boom"


async def test_list_import_runs_filters_and_orders(view: SQLAlchemyIngestionView) -> None:
    """Runs can be filtered by connection and status."""
    first_connection = uuid4()
    second_connection = uuid4()
    first_run = uuid4()
    second_run = uuid4()
    third_run = uuid4()
    await view.register_import_run(
        first_run,
        first_connection,
        uuid4(),
        "src",
        [],
        {},
        {},
        Tracking(UPSTREAM, 1),
    )
    await view.register_import_run(
        second_run,
        first_connection,
        uuid4(),
        "src",
        [],
        {},
        {},
        Tracking(UPSTREAM, 2),
    )
    await view.register_import_run(
        third_run,
        second_connection,
        uuid4(),
        "src",
        [],
        {},
        {},
        Tracking(UPSTREAM, 3),
    )
    await view.finish_import_run(first_run, "succeeded", 1, 1, 1, None, Tracking(UPSTREAM, 4))

    assert [row.run_id for row in await view.list_import_runs(connection_id=first_connection)] == [
        first_run,
        second_run,
    ]
    assert [row.run_id for row in await view.list_import_runs(status="pending")] == [
        second_run,
        third_run,
    ]
    assert [row.run_id for row in await view.list_import_runs(limit=1)] == [first_run]
    assert [row.run_id for row in await view.list_import_runs(limit=1, offset=1)] == [
        second_run
    ]
    assert await view.list_import_runs(connection_id=uuid4()) == []
    assert await view.get_import_run(uuid4()) is None
