"""Application service for the ingestion context."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import structlog
from eventsourcing.application import AggregateNotFoundError
from eventsourcing.asyncio.application import AsyncApplication
from eventsourcing.utils import EnvType

from etlalchemy.catalog.aggregates.errors import DuplicateFieldError
from etlalchemy.catalog.application import CatalogApplication
from etlalchemy.catalog.projection.view import CatalogView
from etlalchemy.ingestion.aggregates.connection import SourceConnection
from etlalchemy.ingestion.aggregates.errors import (
    DuplicateConnectionError,
    IngestionError,
    MissingCredentialError,
    UnknownConnectionError,
    UnknownImportRunError,
    UnknownSourceKindError,
    UnsupportedCredentialSchemeError,
    UnsupportedTypeError,
)
from etlalchemy.ingestion.aggregates.import_run import ImportRun
from etlalchemy.ingestion.ports.data_source import (
    ColumnTypeMapper,
    DataSourceFactory,
    DataSourcePort,
    SourceProfile,
)
from etlalchemy.ingestion.ports.secrets import SecretsResolver, SecretValue
from etlalchemy.ingestion.projection.view import IngestionView
from etlalchemy.shared.credentials import profile_reference
from etlalchemy.shared.logging import bound_context, get_logger


def _elapsed_ms(started: float) -> int:
    """Returns the milliseconds elapsed since ``started``."""
    return int((time.monotonic() - started) * 1000)


@dataclass(frozen=True)
class SourceInspection:
    """One level of a source tree returned by :meth:`IngestionApplication.inspect_source`."""

    node: str
    """Inspected level: ``catalogs``, ``schemas``, ``tables`` or ``columns``."""
    items: list[dict[str, Any]]
    """Inspected nodes, in source order."""


@dataclass(frozen=True)
class ImportPlan:
    """Diff computed by :meth:`IngestionApplication.plan_import` without writing."""

    schema_count: int
    """Number of source schemas the import would visit."""
    table_count: int
    """Number of source tables the import would visit."""
    field_count: int
    """Number of source fields that would be upserted."""
    new_schemas: list[str]
    """Schemas missing from the target catalog."""
    new_tables: list[str]
    """Tables missing from the target catalog, as ``schema.table``."""
    fields_to_change: list[dict[str, Any]]
    """Existing fields whose data type or nullability would change."""
    unsupported_types: list[dict[str, str]]
    """Columns whose source type cannot be mapped, with the applied policy."""
    warnings: list[str]
    """Non-fatal issues such as colliding target tables or unused mappings."""


@dataclass(frozen=True)
class ConnectionTestResult:
    """Result of :meth:`IngestionApplication.test_source_connection`."""

    ok: bool
    """Whether the source answered the probe."""
    latency_ms: int
    """Probe duration in milliseconds."""
    error: str | None = None
    """Error message when the probe failed."""


class IngestionApplication(AsyncApplication[UUID]):
    """Use cases for source connections and catalog imports.

    A connection is addressed by its id. The import use case creates an
    :class:`~etlalchemy.ingestion.aggregates.import_run.ImportRun` before it
    starts and finalises it with one terminal event, so a failed import is
    recorded instead of silently disappearing.
    """

    name = "ingestion_application"
    """Application name; the eventsourcing factories derive table names from it."""

    def __init__(
        self,
        catalog: CatalogApplication,
        catalog_view: CatalogView,
        connections_view: IngestionView,
        factories: dict[str, DataSourceFactory],
        secrets: SecretsResolver,
        env: EnvType | None = None,
    ) -> None:
        """Wires the catalog dependency, source factories and secret resolver."""
        super().__init__(env=env)
        self._catalog = catalog
        self._catalog_view = catalog_view
        self._connections_view = connections_view
        self._factories = dict(factories)
        self._secrets = secrets
        self._log: structlog.stdlib.BoundLogger = get_logger("ingestion.application")

    # -- connection management ---------------------------------------------

    async def create_connection(
        self,
        name: str,
        kind: str,
        endpoint: str,
        credential_ref: str | None = None,
        token: str | None = None,
        default_catalog: str | None = None,
        options: dict[str, str] | None = None,
    ) -> UUID:
        """Creates a connection and returns its id."""
        self._log.info(
            "ingestion.connection.create start",
            name=name,
            kind=kind,
            endpoint=endpoint,
            credential="inline" if token is not None else credential_ref,
        )
        if kind not in self._factories:
            raise UnknownSourceKindError(kind)
        factory = self._factories[kind]
        self._ensure_profile_supported(credential_ref, factory)
        if await self._connections_view.find_connection_by_name(name) is not None:
            raise DuplicateConnectionError(name)
        connection = SourceConnection(
            name=name,
            kind=kind,
            endpoint=endpoint,
            credential_ref=credential_ref,
            token=token,
            default_catalog=default_catalog,
            options=dict(options or {}),
        )
        await self.save(connection)
        self._log.info("ingestion.connection.create done", connection_id=str(connection.id))
        return connection.id

    async def get_connection(self, connection_id: UUID) -> SourceConnection:
        """Returns the connection with the given id."""
        self._log.debug("ingestion.connection.get start", connection_id=str(connection_id))
        try:
            loaded: object = await self.repository.get(connection_id)
        except AggregateNotFoundError as exc:
            raise UnknownConnectionError(str(connection_id)) from exc
        if not isinstance(loaded, SourceConnection):
            raise UnknownConnectionError(str(connection_id))
        self._log.debug("ingestion.connection.get done", name=loaded.name, kind=loaded.kind)
        return loaded

    async def change_connection(
        self,
        connection_id: UUID,
        name: str | None = None,
        endpoint: str | None = None,
        default_catalog: str | None = None,
        options: dict[str, str] | None = None,
    ) -> None:
        """Changes connection metadata without touching the credential."""
        self._log.info(
            "ingestion.connection.change start",
            connection_id=str(connection_id),
            name=name,
            endpoint=endpoint,
        )
        connection = await self.get_connection(connection_id)
        connection.change(name, endpoint, default_catalog, options)
        await self.save(connection)
        self._log.info("ingestion.connection.change done", connection_id=str(connection_id))

    async def rotate_credential(
        self,
        connection_id: UUID,
        credential_ref: str | None = None,
        token: str | None = None,
    ) -> None:
        """Replaces the connection credential."""
        self._log.info(
            "ingestion.credential.rotate start",
            connection_id=str(connection_id),
            credential="inline" if token is not None else credential_ref,
        )
        connection = await self.get_connection(connection_id)
        self._ensure_profile_supported(credential_ref, self._factory(connection))
        connection.rotate_credential(credential_ref, token)
        await self.save(connection)
        self._log.info("ingestion.credential.rotate done", connection_id=str(connection_id))

    async def discard_connection(self, connection_id: UUID) -> None:
        """Marks the connection as discarded."""
        self._log.info("ingestion.connection.discard start", connection_id=str(connection_id))
        connection = await self.get_connection(connection_id)
        connection.discard()
        await self.save(connection)
        self._log.info("ingestion.connection.discard done", connection_id=str(connection_id))

    # -- inspection --------------------------------------------------------

    def source_kinds(self) -> list[str]:
        """Returns the source kinds that have a registered factory."""
        kinds = sorted(self._factories)
        self._log.debug("ingestion.source_kinds", kinds=kinds)
        return kinds

    async def source_profiles(self, kind: str) -> list[SourceProfile]:
        """Returns the local profiles a source kind can authenticate with.

        Args:
            kind: Source kind whose local profile store is read.

        Returns:
            The profiles the machine exposes for that kind; empty when the kind
            stores none.

        Raises:
            UnknownSourceKindError: If no factory is registered for the kind.
            ValueError: If the kind does not support local profiles.
        """
        factory = self._factories.get(kind)
        if factory is None:
            raise UnknownSourceKindError(kind)
        if not factory.profile_capable:
            msg = f"source kind {kind!r} does not support local profiles"
            raise ValueError(msg)
        profiles = await factory.list_profiles()
        self._log.debug("ingestion.source_profiles", kind=kind, count=len(profiles))
        return profiles

    async def inspect_source(
        self,
        connection_id: UUID,
        catalog: str | None = None,
        schema: str | None = None,
        table: str | None = None,
        limit: int = 200,
    ) -> SourceInspection:
        """Inspects one level of the source tree without importing anything."""
        self._log.debug(
            "ingestion.inspect start",
            connection_id=str(connection_id),
            catalog=catalog,
            schema=schema,
            table=table,
        )
        connection = await self.get_connection(connection_id)
        source: DataSourcePort | None = None
        try:
            secret = await self._resolve_credential(connection)
            factory = self._factory(connection)
            source = await factory.build(connection, secret)
            type_mapper = factory.type_mapper(connection)
            inspection: SourceInspection
            if table is not None:
                if schema is None:
                    msg = "inspect_source requires a schema when a table is given"
                    raise IngestionError(msg)
                resolved_catalog = await self._inspect_catalog(source, connection, catalog)
                items: list[dict[str, Any]] = [
                    {
                        "name": column.name,
                        "raw_type": column.raw_type,
                        "mapped_type": self._mapped_type(type_mapper, column.raw_type),
                        "nullable": column.nullable,
                    }
                    for column in (
                        await source.list_columns(
                            resolved_catalog,
                            schema,
                            table,
                        )
                    )[:limit]
                ]
                inspection = SourceInspection(node="columns", items=items)
            elif schema is not None:
                resolved_catalog = await self._inspect_catalog(source, connection, catalog)
                inspection = SourceInspection(
                    node="tables",
                    items=[
                        {"name": name}
                        for name in (await source.list_tables(resolved_catalog, schema))[:limit]
                    ],
                )
            elif catalog is not None:
                inspection = SourceInspection(
                    node="schemas",
                    items=[{"name": name} for name in (await source.list_schemas(catalog))[:limit]],
                )
            else:
                inspection = SourceInspection(
                    node="catalogs",
                    items=[{"name": name} for name in (await source.list_catalogs())[:limit]],
                )
            self._log.debug(
                "ingestion.inspect done",
                node=inspection.node,
                items=len(inspection.items),
            )
            return inspection
        finally:
            if source is not None:
                await source.close()

    async def test_source_connection(self, connection_id: UUID) -> ConnectionTestResult:
        """Checks that the connection can list its catalogs."""
        self._log.debug("ingestion.test_connection start", connection_id=str(connection_id))
        connection = await self.get_connection(connection_id)
        started = time.monotonic()
        source: DataSourcePort | None = None
        try:
            secret = await self._resolve_credential(connection)
            source = await self._factory(connection).build(connection, secret)
            await source.list_catalogs()
            result = ConnectionTestResult(ok=True, latency_ms=_elapsed_ms(started))
        except Exception as exc:
            result = ConnectionTestResult(
                ok=False,
                latency_ms=_elapsed_ms(started),
                error=str(exc),
            )
        finally:
            if source is not None:
                await source.close()
        self._log.info(
            "ingestion.test_connection done",
            connection_id=str(connection_id),
            ok=result.ok,
            latency_ms=result.latency_ms,
        )
        return result

    @staticmethod
    async def _inspect_catalog(
        source: DataSourcePort,
        connection: SourceConnection,
        catalog: str | None,
    ) -> str:
        """Resolves the catalog an inspection should read from."""
        if catalog is not None:
            return catalog
        if connection.default_catalog is not None:
            return connection.default_catalog
        catalogs = await source.list_catalogs()
        if not catalogs:
            msg = "The source exposes no catalog"
            raise IngestionError(msg)
        return catalogs[0]

    @staticmethod
    def _mapped_type(type_mapper: ColumnTypeMapper, raw_type: str) -> str | None:
        """Returns the mapped catalog type, or ``None`` when it is unsupported."""
        try:
            data_type = type_mapper.map(raw_type)
        except UnsupportedTypeError:
            return None
        return None if data_type is None else str(data_type)

    # -- import ------------------------------------------------------------

    async def import_from(
        self,
        connection_id: UUID,
        target_catalog_id: UUID,
        source_catalog: str | None = None,
        include_schemas: list[str] | None = None,
        include_tables: dict[str, list[str]] | None = None,
        schema_mapping: dict[str, str] | None = None,
    ) -> UUID:
        """Imports one source catalog into a catalog and returns the run id."""
        self._log.info(
            "ingestion.import start",
            connection_id=str(connection_id),
            target_catalog_id=str(target_catalog_id),
            source_catalog=source_catalog,
        )
        connection = await self.get_connection(connection_id)
        catalog_name = source_catalog or connection.default_catalog
        schemas = list(include_schemas or [])
        tables = {schema: list(names) for schema, names in (include_tables or {}).items()}
        mapping = dict(schema_mapping or {})
        run = ImportRun(
            connection_id=connection_id,
            target_catalog_id=target_catalog_id,
            source_catalog=catalog_name,
            include_schemas=schemas,
            include_tables=tables,
            schema_mapping=mapping,
        )
        await self.save(run)
        source: DataSourcePort | None = None
        with bound_context(
            run_id=str(run.id),
            connection_id=str(connection_id),
            target_catalog_id=str(target_catalog_id),
        ):
            try:
                secret = await self._resolve_credential(connection)
                source = await self._factory(connection).build(connection, secret)
                await self._do_import(
                    run,
                    source,
                    connection,
                    target_catalog_id,
                    catalog_name,
                    schemas,
                    tables,
                    mapping,
                )
                run.succeed(run.schema_count, run.table_count, run.field_count)
                self._log.info(
                    "ingestion.import done",
                    schemas=run.schema_count,
                    tables=run.table_count,
                    fields=run.field_count,
                )
            except Exception as exc:
                run.fail(str(exc), run.schema_count, run.table_count, run.field_count)
                self._log.exception("ingestion.import failed")
                raise
            finally:
                if source is not None:
                    await source.close()
                await self.save(run)
        return run.id

    async def plan_import(
        self,
        connection_id: UUID,
        target_catalog_id: UUID,
        source_catalog: str | None = None,
        include_schemas: list[str] | None = None,
        include_tables: dict[str, list[str]] | None = None,
        schema_mapping: dict[str, str] | None = None,
    ) -> ImportPlan:
        """Computes what an import would change without writing to the catalog."""
        self._log.debug(
            "ingestion.plan start",
            connection_id=str(connection_id),
            target_catalog_id=str(target_catalog_id),
            source_catalog=source_catalog,
        )
        connection = await self.get_connection(connection_id)
        catalog_name = source_catalog or connection.default_catalog
        schemas = list(include_schemas or [])
        tables_filter = {schema: list(names) for schema, names in (include_tables or {}).items()}
        mapping = dict(schema_mapping or {})
        source: DataSourcePort | None = None
        try:
            secret = await self._resolve_credential(connection)
            factory = self._factory(connection)
            source = await factory.build(connection, secret)
            type_mapper = factory.type_mapper(connection)
            schema_count = 0
            table_count = 0
            field_count = 0
            new_schemas: list[str] = []
            new_tables: list[str] = []
            fields_to_change: list[dict[str, Any]] = []
            unsupported_types: list[dict[str, str]] = []
            warnings: list[str] = []
            seen_targets: set[tuple[str, str]] = set()
            applied_mapping: set[str] = set()
            for src_catalog, source_schema in await self._source_schemas(source, catalog_name):
                if tables_filter:
                    if source_schema not in tables_filter:
                        continue
                    if not tables_filter[source_schema]:
                        continue
                elif schemas and source_schema not in schemas:
                    continue
                target_schema = mapping.get(source_schema, source_schema)
                applied_mapping.add(source_schema)
                schema_id = await self._catalog_view.find_schema_id(
                    target_catalog_id,
                    target_schema,
                )
                if schema_id is None and target_schema not in new_schemas:
                    new_schemas.append(target_schema)
                schema_count += 1
                table_names = await source.list_tables(src_catalog, source_schema)
                if tables_filter:
                    wanted = tables_filter[source_schema]
                    table_names = [name for name in table_names if name in wanted]
                for table_name in table_names:
                    target_key = (target_schema, table_name)
                    if target_key in seen_targets:
                        warnings.append(
                            f"Multiple source tables map to target table "
                            f"{target_schema}.{table_name}; only the first is planned"
                        )
                        continue
                    seen_targets.add(target_key)
                    table_count += 1
                    qualified = f"{target_schema}.{table_name}"
                    existing: dict[str, Any]
                    table_id = (
                        None
                        if schema_id is None
                        else await self._catalog_view.find_table_id(schema_id, table_name)
                    )
                    if table_id is None:
                        new_tables.append(qualified)
                        existing = {}
                    else:
                        existing = {
                            row.name: row for row in await self._catalog_view.list_fields(table_id)
                        }
                    for column in await source.list_columns(
                        src_catalog,
                        source_schema,
                        table_name,
                    ):
                        try:
                            data_type = type_mapper.map(column.raw_type)
                        except UnsupportedTypeError:
                            unsupported_types.append(
                                {
                                    "table": qualified,
                                    "column": column.name,
                                    "raw_type": column.raw_type,
                                    "policy": connection.options.get(
                                        "type_policy",
                                        "fail",
                                    ),
                                }
                            )
                            continue
                        if data_type is None:
                            unsupported_types.append(
                                {
                                    "table": qualified,
                                    "column": column.name,
                                    "raw_type": column.raw_type,
                                    "policy": "skip",
                                }
                            )
                            continue
                        field_count += 1
                        current = existing.get(column.name)
                        if current is not None and (
                            current.data_type != data_type or current.nullable != column.nullable
                        ):
                            fields_to_change.append(
                                {
                                    "table": qualified,
                                    "column": column.name,
                                    "from_type": str(current.data_type),
                                    "to_type": str(data_type),
                                    "from_nullable": current.nullable,
                                    "to_nullable": column.nullable,
                                }
                            )
            for source_schema in mapping:
                if source_schema not in applied_mapping:
                    warnings.append(
                        f"schema_mapping entry {source_schema!r} was not applied because "
                        "the schema is not imported"
                    )
            plan = ImportPlan(
                schema_count=schema_count,
                table_count=table_count,
                field_count=field_count,
                new_schemas=new_schemas,
                new_tables=new_tables,
                fields_to_change=fields_to_change,
                unsupported_types=unsupported_types,
                warnings=warnings,
            )
            self._log.info(
                "ingestion.plan done",
                schemas=plan.schema_count,
                tables=plan.table_count,
                fields=plan.field_count,
                new_schemas=len(plan.new_schemas),
                new_tables=len(plan.new_tables),
                warnings=len(plan.warnings),
            )
            return plan
        finally:
            if source is not None:
                await source.close()

    async def get_import_run(self, run_id: UUID) -> ImportRun | None:
        """Returns the import run with the given id, or ``None``."""
        self._log.debug("ingestion.run.get start", run_id=str(run_id))
        try:
            loaded: object = await self.repository.get(run_id)
        except AggregateNotFoundError:
            return None
        return loaded if isinstance(loaded, ImportRun) else None

    async def abandon_import_run(self, run_id: UUID, reason: str) -> None:
        """Marks a stale pending import run as abandoned."""
        self._log.info("ingestion.run.abandon start", run_id=str(run_id), reason=reason)
        run = await self.get_import_run(run_id)
        if run is None:
            raise UnknownImportRunError(str(run_id))
        run.abandon(reason)
        await self.save(run)
        self._log.info("ingestion.run.abandon done", run_id=str(run_id))

    async def _resolve_credential(self, connection: SourceConnection) -> SecretValue | None:
        """Returns the credential, or ``None`` for a local profile connection."""
        profile = profile_reference(connection.credential_ref)
        self._log.debug(
            "ingestion.credential.resolve",
            connection_id=str(connection.id),
            source=(
                "profile"
                if profile is not None
                else "inline"
                if connection.token is not None
                else connection.credential_ref
            ),
        )
        if profile is not None:
            return None
        if connection.token is not None:
            return SecretValue(connection.token)
        if connection.credential_ref is not None:
            return await self._secrets.resolve(connection.credential_ref)
        raise MissingCredentialError(str(connection.id))

    @staticmethod
    def _ensure_profile_supported(
        credential_ref: str | None,
        factory: DataSourceFactory,
    ) -> None:
        """Rejects a profile reference for a kind that cannot resolve it."""
        if profile_reference(credential_ref) is None or factory.profile_capable:
            return
        msg = f"source kind {factory.kind!r} does not support profile references"
        raise UnsupportedCredentialSchemeError(msg)

    def _factory(self, connection: SourceConnection) -> DataSourceFactory:
        """Returns the factory registered for the connection's kind."""
        self._log.debug("ingestion.factory.resolve", kind=connection.kind)
        try:
            return self._factories[connection.kind]
        except KeyError:
            raise UnknownSourceKindError(connection.kind) from None

    async def _do_import(
        self,
        run: ImportRun,
        source: DataSourcePort,
        connection: SourceConnection,
        target_catalog_id: UUID,
        source_catalog: str | None,
        include_schemas: list[str],
        include_tables: dict[str, list[str]],
        schema_mapping: dict[str, str],
    ) -> None:
        """Walks the source tree and upserts it into the target catalog."""
        type_mapper = self._factory(connection).type_mapper(connection)
        known_schemas: dict[str, UUID] = {}
        known_tables: dict[tuple[str, str], UUID] = {}
        for src_catalog, source_schema in await self._source_schemas(source, source_catalog):
            if include_tables:
                if source_schema not in include_tables:
                    continue
                if not include_tables[source_schema]:
                    continue
            elif include_schemas and source_schema not in include_schemas:
                continue
            target_schema = schema_mapping.get(source_schema, source_schema)
            schema_id = known_schemas.get(target_schema)
            if schema_id is None:
                schema_id = await self._catalog_view.find_schema_id(
                    target_catalog_id,
                    target_schema,
                )
                if schema_id is None:
                    schema_id = await self._catalog.create_schema(
                        target_catalog_id,
                        target_schema,
                    )
                known_schemas[target_schema] = schema_id
            run.record_schema()
            table_names = await source.list_tables(src_catalog, source_schema)
            if include_tables:
                wanted = include_tables[source_schema]
                table_names = [name for name in table_names if name in wanted]
            for table_name in table_names:
                table_key = (target_schema, table_name)
                table_id = known_tables.get(table_key)
                if table_id is None:
                    table_id = await self._catalog_view.find_table_id(schema_id, table_name)
                    if table_id is None:
                        table_id = await self._catalog.add_table(
                            target_catalog_id,
                            schema_id,
                            table_name,
                        )
                    known_tables[table_key] = table_id
                run.record_table()
                await self._import_columns(
                    run,
                    source,
                    type_mapper,
                    target_catalog_id,
                    schema_id,
                    table_id,
                    src_catalog,
                    source_schema,
                    table_name,
                )

    @staticmethod
    async def _source_schemas(
        source: DataSourcePort,
        source_catalog: str | None,
    ) -> list[tuple[str, str]]:
        """Returns the ``(catalog, schema)`` pairs an import must visit."""
        if source_catalog is not None:
            return [
                (source_catalog, schema_name)
                for schema_name in await source.list_schemas(source_catalog)
            ]
        return [
            (catalog_name, schema_name)
            for catalog_name in await source.list_catalogs()
            for schema_name in await source.list_schemas(catalog_name)
        ]

    async def _import_columns(
        self,
        run: ImportRun,
        source: DataSourcePort,
        type_mapper: ColumnTypeMapper,
        target_catalog_id: UUID,
        schema_id: UUID,
        table_id: UUID,
        src_catalog: str,
        source_schema: str,
        table_name: str,
    ) -> None:
        """Upserts the columns of one source table into the target table."""
        for column in await source.list_columns(src_catalog, source_schema, table_name):
            data_type = type_mapper.map(column.raw_type)
            if data_type is None:
                continue
            self._log.debug(
                "ingestion.import column",
                table=f"{source_schema}.{table_name}",
                column=column.name,
                data_type=str(data_type),
            )
            try:
                await self._catalog.add_field(
                    target_catalog_id,
                    schema_id,
                    table_id,
                    column.name,
                    data_type,
                    column.nullable,
                )
            except DuplicateFieldError:
                await self._catalog.change_field(
                    target_catalog_id,
                    schema_id,
                    table_id,
                    column.name,
                    data_type,
                    column.nullable,
                )
            run.record_field()
