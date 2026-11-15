"""Tests for the ingestion application use cases."""

from uuid import UUID, uuid4

import pytest

from etlalchemy.catalog.aggregates.errors import UnknownSchemaError
from etlalchemy.ingestion import (
    DiscardedError,
    DuplicateConnectionError,
    IngestionApplication,
    IngestionError,
    InvalidImportRunStateError,
    SourceConnection,
    UnknownConnectionError,
    UnknownImportRunError,
    UnknownSourceKindError,
    UnsupportedCredentialSchemeError,
)
from etlalchemy.ingestion.aggregates.import_run import ImportRun
from etlalchemy.ingestion.ports.data_source import ColumnInfo
from tests.ingestion.support import (
    FakeConnectionsView,
    FakeSource,
    FakeSourceFactory,
    RecordingCatalogApplication,
)


async def create_connection(
    application: IngestionApplication,
    name: str = "warehouse",
    **overrides: object,
) -> UUID:
    """Creates a connection with defaults suitable for the fake factory."""
    values: dict[str, object] = {
        "kind": "fake",
        "endpoint": "https://example.test",
        "token": "s3cr3t",
    }
    values.update(overrides)
    return await application.create_connection(name=name, **values)


def source_tree() -> dict[str, dict[str, dict[str, list[ColumnInfo]]]]:
    """Returns a one-catalog, one-schema, one-table source tree."""
    return {
        "src": {
            "sales": {
                "orders": [
                    ColumnInfo(name="id", raw_type="BIGINT", nullable=False),
                    ColumnInfo(name="amount", raw_type="decimal(10,2)", nullable=True),
                    ColumnInfo(name="payload", raw_type="skip", nullable=True),
                ]
            }
        }
    }


def multi_schema_tree() -> dict[str, dict[str, dict[str, list[ColumnInfo]]]]:
    """Returns a source tree with three schemas and several tables."""
    return {
        "src": {
            "sales": {
                "orders": [ColumnInfo("id", "BIGINT", False)],
                "customers": [ColumnInfo("id", "BIGINT", False)],
            },
            "public": {"users": [ColumnInfo("id", "BIGINT", False)]},
            "audit": {"events": [ColumnInfo("id", "BIGINT", False)]},
        }
    }


async def latest_run_id(application: IngestionApplication, connection_id: UUID) -> UUID:
    """Returns the id of the most recent import run in the event store."""
    notifications = await application.recorder.select_notifications(1, 100)
    return next(
        notification.originator_id
        for notification in reversed(notifications)
        if notification.originator_id != connection_id
    )


async def test_create_connection_persists_a_started_event(
    application: IngestionApplication,
) -> None:
    """await create_connection() saves the new aggregate and returns its id."""
    connection_id = await create_connection(application)

    connection = await application.get_connection(connection_id)

    assert isinstance(connection, SourceConnection)
    assert connection.name == "warehouse"
    assert connection.token == "s3cr3t"
    assert connection.version == 1
    assert len(list(await application.events.get(connection_id))) == 1


async def test_create_connection_rejects_a_duplicate_name(
    application: IngestionApplication,
    connections_view: FakeConnectionsView,
) -> None:
    """A name already present in the read model is rejected without persisting."""
    connections_view.by_name["warehouse"] = uuid4()

    with pytest.raises(DuplicateConnectionError, match="warehouse"):
        await create_connection(application)

    assert await application.recorder.max_notification_id() is None


async def test_create_connection_rejects_an_unknown_kind(
    application: IngestionApplication,
) -> None:
    """A kind without a registered factory is rejected without persisting."""
    with pytest.raises(UnknownSourceKindError, match="databricks"):
        await create_connection(application, kind="databricks")

    assert await application.recorder.max_notification_id() is None


async def test_create_connection_validates_the_credential(
    application: IngestionApplication,
) -> None:
    """An ambiguous credential is rejected without persisting."""
    with pytest.raises(IngestionError, match="exactly one"):
        await create_connection(application, credential_ref="env:DBX_TOKEN")

    assert await application.recorder.max_notification_id() is None


async def test_a_profile_connection_resolves_no_secret(
    application: IngestionApplication,
    factory: FakeSourceFactory,
) -> None:
    """A profile reference skips the secret resolver and builds with ``None``."""
    connection_id = await create_connection(
        application,
        token=None,
        credential_ref="profile:team",
        endpoint="",
    )

    result = await application.test_source_connection(connection_id)

    assert result.ok is True
    assert factory.secrets == [None]


async def test_a_profile_reference_is_rejected_for_a_kind_without_profiles(
    application: IngestionApplication,
    factory: FakeSourceFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A kind that cannot read local profiles rejects the reference."""
    monkeypatch.setattr(factory, "profile_capable", False)

    with pytest.raises(UnsupportedCredentialSchemeError, match="profile"):
        await create_connection(
            application,
            token=None,
            credential_ref="profile:team",
            endpoint="",
        )


async def test_source_profiles_lists_the_local_profiles(
    application: IngestionApplication,
) -> None:
    """The use case returns what the factory reads from the local store."""
    profiles = await application.source_profiles("fake")

    assert [(profile.name, profile.host) for profile in profiles] == [
        ("fake", "https://fake.test")
    ]


async def test_source_profiles_rejects_a_kind_without_profiles(
    application: IngestionApplication,
    factory: FakeSourceFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A kind without a local profile store rejects the read."""
    monkeypatch.setattr(factory, "profile_capable", False)

    with pytest.raises(ValueError, match="does not support local profiles"):
        await application.source_profiles("fake")


async def test_get_connection_rejects_an_unknown_id(
    application: IngestionApplication,
) -> None:
    """Reading an aggregate that was never saved raises UnknownConnectionError."""
    with pytest.raises(UnknownConnectionError):
        await application.get_connection(uuid4())


async def test_change_connection_updates_metadata(
    application: IngestionApplication,
) -> None:
    """Changing a connection records one event."""
    connection_id = await create_connection(application)

    await application.change_connection(
        connection_id,
        name="renamed",
        default_catalog="main",
    )

    connection = await application.get_connection(connection_id)
    assert connection.name == "renamed"
    assert connection.default_catalog == "main"
    assert connection.version == 2


async def test_change_connection_requires_a_field(
    application: IngestionApplication,
) -> None:
    """A failing use case leaves the stored aggregate untouched."""
    connection_id = await create_connection(application)

    with pytest.raises(ValueError, match="at least one"):
        await application.change_connection(connection_id)

    assert (await application.get_connection(connection_id)).version == 1


async def test_rotate_credential_replaces_the_credential(
    application: IngestionApplication,
) -> None:
    """Rotation switches to an external reference."""
    connection_id = await create_connection(application)

    await application.rotate_credential(connection_id, credential_ref="env:DBX_TOKEN")

    connection = await application.get_connection(connection_id)
    assert connection.credential_ref == "env:DBX_TOKEN"
    assert connection.token is None
    assert connection.version == 2


async def test_rotate_credential_validates_its_input(
    application: IngestionApplication,
) -> None:
    """An ambiguous rotation is rejected without persisting."""
    connection_id = await create_connection(application)

    with pytest.raises(IngestionError, match="exactly one"):
        await application.rotate_credential(
            connection_id,
            credential_ref="env:DBX_TOKEN",
            token="other",
        )

    assert (await application.get_connection(connection_id)).version == 1


async def test_discard_connection_blocks_later_commands(
    application: IngestionApplication,
) -> None:
    """A discarded connection rejects every later command."""
    connection_id = await create_connection(application)

    await application.discard_connection(connection_id)

    assert (await application.get_connection(connection_id)).version == 2
    with pytest.raises(DiscardedError):
        await application.change_connection(connection_id, name="other")
    with pytest.raises(DiscardedError):
        await application.discard_connection(connection_id)


async def test_import_from_upserts_the_source_tree(
    application: IngestionApplication,
    catalog: RecordingCatalogApplication,
    source: FakeSource,
    factory: FakeSourceFactory,
) -> None:
    """A successful import records the run and upserts schemas, tables and fields."""
    catalog_id = await catalog.create_catalog("target")
    connection_id = await create_connection(application)
    source.catalogs = source_tree()

    run_id = await application.import_from(connection_id, catalog_id, source_catalog="src")

    run = await application.repository.get(run_id)
    assert isinstance(run, ImportRun)
    assert run.status == "succeeded"
    assert (run.schema_count, run.table_count, run.field_count) == (1, 1, 2)

    schema = await catalog.get_schema(catalog_id, "sales")
    table = await catalog.get_table(catalog_id, schema.id, "orders")
    assert set(table.fields) == {"id", "amount"}
    assert table.fields["id"].nullable is False
    assert str(table.fields["amount"].data_type) == "decimal(10,2)"

    assert factory.secrets == ["s3cr3t"]
    assert source.closed is True


async def test_import_from_uses_the_connection_default_catalog(
    application: IngestionApplication,
    catalog: RecordingCatalogApplication,
    source: FakeSource,
) -> None:
    """Without an explicit source catalog the connection default is imported."""
    catalog_id = await catalog.create_catalog("target")
    connection_id = await create_connection(application, default_catalog="src")
    source.catalogs = {
        "src": {"sales": {"orders": [ColumnInfo("id", "BIGINT", False)]}},
        "other": {"hr": {"people": [ColumnInfo("id", "BIGINT", False)]}},
    }

    run_id = await application.import_from(connection_id, catalog_id)

    run = await application.repository.get(run_id)
    assert run.source_catalog == "src"
    assert run.schema_count == 1
    assert list((await catalog.get_catalog(catalog_id)).schemas) == ["sales"]
    with pytest.raises(UnknownSchemaError):
        await catalog.get_schema(catalog_id, "hr")


async def test_import_from_walks_every_catalog_without_a_source_catalog(
    application: IngestionApplication,
    catalog: RecordingCatalogApplication,
    source: FakeSource,
) -> None:
    """Without a source catalog and default every catalog is imported."""
    catalog_id = await catalog.create_catalog("target")
    connection_id = await create_connection(application)
    source.catalogs = {
        "one": {"sales": {"orders": [ColumnInfo("id", "BIGINT", False)]}},
        "two": {"hr": {"people": [ColumnInfo("id", "BIGINT", False)]}},
    }

    run_id = await application.import_from(connection_id, catalog_id)

    run = await application.repository.get(run_id)
    assert (run.schema_count, run.table_count, run.field_count) == (2, 2, 2)
    assert set((await catalog.get_catalog(catalog_id)).schemas) == {"sales", "hr"}


async def test_import_from_honours_include_schemas(
    application: IngestionApplication,
    catalog: RecordingCatalogApplication,
    source: FakeSource,
) -> None:
    """Only the listed schemas are imported."""
    catalog_id = await catalog.create_catalog("target")
    connection_id = await create_connection(application)
    source.catalogs = {
        "src": {
            "sales": {"orders": [ColumnInfo("id", "BIGINT", False)]},
            "marketing": {"leads": [ColumnInfo("id", "BIGINT", False)]},
        }
    }

    run_id = await application.import_from(
        connection_id,
        catalog_id,
        source_catalog="src",
        include_schemas=["sales"],
    )

    run = await application.repository.get(run_id)
    assert run.schema_count == 1
    assert list((await catalog.get_catalog(catalog_id)).schemas) == ["sales"]


async def test_a_failed_import_is_recorded_and_re_raised(
    application: IngestionApplication,
    catalog: RecordingCatalogApplication,
    source: FakeSource,
) -> None:
    """A source error finalises the run as failed before it propagates."""
    catalog_id = await catalog.create_catalog("target")
    connection_id = await create_connection(application)
    source.catalogs = {"src": {"sales": {}}}
    source.fail_with = "boom"

    with pytest.raises(RuntimeError, match="boom"):
        await application.import_from(connection_id, catalog_id, source_catalog="src")

    run = await application.repository.get(await latest_run_id(application, connection_id))
    assert isinstance(run, ImportRun)
    assert run.status == "failed"
    assert run.error == "boom"
    assert source.closed is True


async def test_import_from_resolves_an_external_credential(
    application: IngestionApplication,
    catalog: RecordingCatalogApplication,
    source: FakeSource,
    factory: FakeSourceFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``credential_ref`` is resolved through the secrets resolver."""
    monkeypatch.setenv("DBX_TOKEN", "from-env")
    catalog_id = await catalog.create_catalog("target")
    connection_id = await create_connection(
        application,
        token=None,
        credential_ref="env:DBX_TOKEN",
    )
    source.catalogs = {"src": {"sales": {}}}

    await application.import_from(connection_id, catalog_id, source_catalog="src")

    assert factory.secrets == ["from-env"]


async def test_import_from_records_an_unresolvable_credential(
    application: IngestionApplication,
    catalog: RecordingCatalogApplication,
    source: FakeSource,
) -> None:
    """An unsupported credential scheme finalises the run as failed."""
    catalog_id = await catalog.create_catalog("target")
    connection_id = await create_connection(
        application,
        token=None,
        credential_ref="vault:secret/x",
    )
    source.catalogs = {"src": {"sales": {}}}

    with pytest.raises(UnsupportedCredentialSchemeError):
        await application.import_from(connection_id, catalog_id, source_catalog="src")

    run = await application.repository.get(await latest_run_id(application, connection_id))
    assert run.status == "failed"
    assert "vault" in run.error


async def test_import_from_is_idempotent(
    application: IngestionApplication,
    catalog: RecordingCatalogApplication,
    source: FakeSource,
    factory: FakeSourceFactory,
) -> None:
    """Importing twice reuses the schema and table streams."""
    catalog_id = await catalog.create_catalog("target")
    connection_id = await create_connection(application)
    source.catalogs = {
        "src": {"sales": {"orders": [ColumnInfo("id", "BIGINT", False)]}}
    }

    first = await application.import_from(connection_id, catalog_id, source_catalog="src")
    second = await application.import_from(connection_id, catalog_id, source_catalog="src")

    assert (await application.repository.get(first)).status == "succeeded"
    assert (await application.repository.get(second)).status == "succeeded"
    schema = await catalog.get_schema(catalog_id, "sales")
    table = await catalog.get_table(catalog_id, schema.id, "orders")
    assert list(table.fields) == ["id"]
    assert table.version == 2
    assert factory.secrets == ["s3cr3t", "s3cr3t"]


async def test_source_kinds_lists_the_registered_factories(
    application: IngestionApplication,
) -> None:
    """The application exposes the kinds it can build."""
    assert application.source_kinds() == ["fake"]


async def test_inspect_source_walks_the_source_tree(
    application: IngestionApplication,
    source: FakeSource,
) -> None:
    """Inspection returns one level of the source at a time."""
    connection_id = await create_connection(application)
    source.catalogs = source_tree()

    catalogs = await application.inspect_source(connection_id)
    assert catalogs.node == "catalogs"
    assert catalogs.items == [{"name": "src"}]

    schemas = await application.inspect_source(connection_id, catalog="src")
    assert schemas.node == "schemas"
    assert schemas.items == [{"name": "sales"}]

    tables = await application.inspect_source(connection_id, catalog="src", schema="sales")
    assert tables.node == "tables"
    assert tables.items == [{"name": "orders"}]

    columns = await application.inspect_source(
        connection_id,
        catalog="src",
        schema="sales",
        table="orders",
    )
    assert columns.node == "columns"
    assert [
        (item["name"], item["mapped_type"], item["nullable"]) for item in columns.items
    ] == [
        ("id", "bigint", False),
        ("amount", "decimal(10,2)", True),
        ("payload", None, True),
    ]


async def test_inspect_source_uses_the_default_catalog(
    application: IngestionApplication,
    source: FakeSource,
) -> None:
    """A missing catalog falls back to the connection default."""
    connection_id = await create_connection(application, default_catalog="src")
    source.catalogs = source_tree()

    result = await application.inspect_source(connection_id, schema="sales")

    assert result.node == "tables"
    assert result.items == [{"name": "orders"}]


async def test_inspect_source_requires_a_schema_for_a_table(
    application: IngestionApplication,
) -> None:
    """Inspecting columns without a schema is rejected."""
    connection_id = await create_connection(application)

    with pytest.raises(IngestionError, match="schema"):
        await application.inspect_source(connection_id, table="orders")


async def test_plan_import_reports_the_diff(
    application: IngestionApplication,
    catalog: RecordingCatalogApplication,
    source: FakeSource,
) -> None:
    """A dry run reports new objects without writing to the catalog."""
    catalog_id = await catalog.create_catalog("target")
    connection_id = await create_connection(application)
    source.catalogs = source_tree()

    plan = await application.plan_import(connection_id, catalog_id, source_catalog="src")

    assert (plan.schema_count, plan.table_count, plan.field_count) == (1, 1, 2)
    assert plan.new_schemas == ["sales"]
    assert plan.new_tables == ["sales.orders"]
    assert plan.fields_to_change == []
    assert [
        (entry["column"], entry["policy"]) for entry in plan.unsupported_types
    ] == [("payload", "skip")]
    assert (await catalog.get_catalog(catalog_id)).schemas == {}

    await application.import_from(connection_id, catalog_id, source_catalog="src")
    second = await application.plan_import(connection_id, catalog_id, source_catalog="src")
    assert second.new_schemas == []
    assert second.new_tables == []
    assert second.fields_to_change == []


async def test_plan_import_reports_changed_fields(
    application: IngestionApplication,
    catalog: RecordingCatalogApplication,
    source: FakeSource,
) -> None:
    """A dry run reports existing fields whose type or nullability changes."""
    catalog_id = await catalog.create_catalog("target")
    connection_id = await create_connection(application)
    source.catalogs = source_tree()
    await application.import_from(connection_id, catalog_id, source_catalog="src")

    source.catalogs["src"]["sales"]["orders"][1] = ColumnInfo(
        name="amount",
        raw_type="text",
        nullable=False,
    )

    plan = await application.plan_import(connection_id, catalog_id, source_catalog="src")

    assert plan.fields_to_change == [
        {
            "table": "sales.orders",
            "column": "amount",
            "from_type": "decimal(10,2)",
            "to_type": "text",
            "from_nullable": True,
            "to_nullable": False,
        }
    ]


async def test_plan_import_reports_unsupported_types(
    application: IngestionApplication,
    catalog: RecordingCatalogApplication,
    source: FakeSource,
) -> None:
    """A dry run reports columns that cannot be mapped."""
    catalog_id = await catalog.create_catalog("target")
    connection_id = await create_connection(application)
    source.catalogs = {
        "src": {"sales": {"orders": [ColumnInfo("payload", "unsupported", True)]}}
    }

    plan = await application.plan_import(connection_id, catalog_id, source_catalog="src")

    assert plan.unsupported_types == [
        {
            "table": "sales.orders",
            "column": "payload",
            "raw_type": "unsupported",
            "policy": "fail",
        }
    ]
    assert plan.field_count == 0


async def test_test_source_connection_reports_success_and_failure(
    application: IngestionApplication,
    source: FakeSource,
) -> None:
    """The probe reports success, then the source error without raising."""
    connection_id = await create_connection(application)
    source.catalogs = source_tree()

    success = await application.test_source_connection(connection_id)
    assert success.ok is True
    assert success.error is None
    assert success.latency_ms >= 0

    source.fail_with = "boom"
    failure = await application.test_source_connection(connection_id)
    assert failure.ok is False
    assert failure.error == "boom"


async def test_get_and_abandon_import_run(application: IngestionApplication) -> None:
    """A stale pending run can be looked up and abandoned."""
    run = ImportRun(connection_id=uuid4(), target_catalog_id=uuid4())
    await application.save(run)

    loaded = await application.get_import_run(run.id)
    assert isinstance(loaded, ImportRun)
    assert loaded.id == run.id

    await application.abandon_import_run(run.id, "process crashed")

    abandoned = await application.get_import_run(run.id)
    assert abandoned is not None
    assert abandoned.status == "abandoned"
    assert abandoned.error == "process crashed"
    assert await application.get_import_run(uuid4()) is None


async def test_abandon_import_run_rejects_unknown_and_finished_runs(
    application: IngestionApplication,
) -> None:
    """Abandoning needs an existing pending run."""
    with pytest.raises(UnknownImportRunError):
        await application.abandon_import_run(uuid4(), "crashed")

    run = ImportRun(connection_id=uuid4(), target_catalog_id=uuid4())
    await application.save(run)
    await application.abandon_import_run(run.id, "crashed")

    with pytest.raises(InvalidImportRunStateError, match="abandoned"):
        await application.abandon_import_run(run.id, "again")


async def test_import_from_imports_only_the_selected_tables(
    application: IngestionApplication,
    catalog: RecordingCatalogApplication,
    source: FakeSource,
) -> None:
    """include_tables restricts the import to the listed source tables."""
    catalog_id = await catalog.create_catalog("target")
    connection_id = await create_connection(application)
    source.catalogs = multi_schema_tree()

    run_id = await application.import_from(
        connection_id,
        catalog_id,
        source_catalog="src",
        include_tables={"sales": ["orders"]},
    )

    run = await application.repository.get(run_id)
    assert run.status == "succeeded"
    assert (run.schema_count, run.table_count, run.field_count) == (1, 1, 1)
    assert run.include_tables == {"sales": ["orders"]}
    assert list((await catalog.get_catalog(catalog_id)).schemas) == ["sales"]
    assert list((await catalog.get_schema(catalog_id, "sales")).tables) == ["orders"]


async def test_import_from_skips_a_schema_with_an_empty_table_list(
    application: IngestionApplication,
    catalog: RecordingCatalogApplication,
    source: FakeSource,
) -> None:
    """An empty table list explicitly skips a schema."""
    catalog_id = await catalog.create_catalog("target")
    connection_id = await create_connection(application)
    source.catalogs = multi_schema_tree()

    await application.import_from(
        connection_id,
        catalog_id,
        source_catalog="src",
        include_tables={"sales": [], "public": ["users"]},
    )

    assert list((await catalog.get_catalog(catalog_id)).schemas) == ["public"]
    assert list((await catalog.get_schema(catalog_id, "public")).tables) == ["users"]


async def test_include_tables_overrides_include_schemas(
    application: IngestionApplication,
    catalog: RecordingCatalogApplication,
    source: FakeSource,
) -> None:
    """A non-empty include_tables ignores include_schemas."""
    catalog_id = await catalog.create_catalog("target")
    connection_id = await create_connection(application)
    source.catalogs = multi_schema_tree()

    await application.import_from(
        connection_id,
        catalog_id,
        source_catalog="src",
        include_schemas=["public"],
        include_tables={"sales": ["customers"]},
    )

    assert list((await catalog.get_catalog(catalog_id)).schemas) == ["sales"]
    assert list((await catalog.get_schema(catalog_id, "sales")).tables) == ["customers"]


async def test_import_from_maps_source_schemas_to_target_names(
    application: IngestionApplication,
    catalog: RecordingCatalogApplication,
    source: FakeSource,
) -> None:
    """schema_mapping renames source schemas in the target catalog."""
    catalog_id = await catalog.create_catalog("target")
    connection_id = await create_connection(application)
    source.catalogs = multi_schema_tree()

    run_id = await application.import_from(
        connection_id,
        catalog_id,
        source_catalog="src",
        include_tables={"sales": ["orders"], "public": ["users"]},
        schema_mapping={"sales": "sales_raw", "public": "shared"},
    )

    run = await application.repository.get(run_id)
    assert run.schema_mapping == {"sales": "sales_raw", "public": "shared"}
    assert set((await catalog.get_catalog(catalog_id)).schemas) == {"sales_raw", "shared"}
    assert list((await catalog.get_schema(catalog_id, "sales_raw")).tables) == ["orders"]
    assert list((await catalog.get_schema(catalog_id, "shared")).tables) == ["users"]


async def test_plan_import_reports_target_names_and_warnings(
    application: IngestionApplication,
    catalog: RecordingCatalogApplication,
    source: FakeSource,
) -> None:
    """The plan reports target-side names and warns about collisions and unused maps."""
    catalog_id = await catalog.create_catalog("target")
    connection_id = await create_connection(application)
    source.catalogs = {
        "src": {
            "a": {"t": [ColumnInfo("id", "BIGINT", False)]},
            "b": {"t": [ColumnInfo("id", "BIGINT", False)]},
            "skipped": {"t": [ColumnInfo("id", "BIGINT", False)]},
        }
    }

    plan = await application.plan_import(
        connection_id,
        catalog_id,
        source_catalog="src",
        include_tables={"a": ["t"], "b": ["t"], "skipped": []},
        schema_mapping={"a": "x", "b": "x", "skipped": "y", "missing": "z"},
    )

    assert (plan.schema_count, plan.table_count, plan.field_count) == (2, 1, 1)
    assert plan.new_schemas == ["x"]
    assert plan.new_tables == ["x.t"]
    assert any(
        "Multiple source tables map to target table x.t" in warning
        for warning in plan.warnings
    )
    assert any(
        "'skipped'" in warning and "not applied" in warning for warning in plan.warnings
    )
    assert any(
        "'missing'" in warning and "not applied" in warning for warning in plan.warnings
    )


async def test_import_from_merges_sources_that_map_to_the_same_target(
    application: IngestionApplication,
    catalog: RecordingCatalogApplication,
    source: FakeSource,
) -> None:
    """Two source tables mapping to one target table merge their fields."""
    catalog_id = await catalog.create_catalog("target")
    connection_id = await create_connection(application)
    source.catalogs = {
        "src": {
            "a": {"t": [ColumnInfo("id", "BIGINT", False)]},
            "b": {"t": [ColumnInfo("code", "TEXT", True)]},
        }
    }

    run_id = await application.import_from(
        connection_id,
        catalog_id,
        source_catalog="src",
        include_tables={"a": ["t"], "b": ["t"]},
        schema_mapping={"a": "x", "b": "x"},
    )

    run = await application.repository.get(run_id)
    assert run.status == "succeeded"
    schema = await catalog.get_schema(catalog_id, "x")
    assert list(schema.tables) == ["t"]
    table = await catalog.get_table(catalog_id, "x", "t")
    assert set(table.fields) == {"id", "code"}
