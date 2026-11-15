"""Asynchronous SQLAlchemy implementation of the ingestion read model.

SQLAlchemy Core builds the table definitions and the DML statements; they are
executed on the async engine of
:class:`~eventsourcing.asyncio.sqlalchemy.AsyncSQLAlchemyDatastore`, so the view
change and its tracking record still share one transaction. The same class serves
SQLite (``aiosqlite``) and PostgreSQL (``psycopg``); only the upsert dialect and
the column migration differ.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from eventsourcing.asyncio.sqlalchemy import (
    AsyncSQLAlchemyDatastore,
    AsyncSQLAlchemyTrackingRecorder,
)
from sqlalchemy import Select, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from etlalchemy.ingestion.projection.tables import (
    ingestion_connections,
    ingestion_import_runs,
    metadata,
)
from etlalchemy.ingestion.projection.view import (
    ConnectionRow,
    ImportRunRow,
    IngestionView,
    as_uuid,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from eventsourcing.persistence import Tracking
    from sqlalchemy import Table
    from sqlalchemy.ext.asyncio import AsyncConnection

IMPORT_RUN_COLUMNS = ("include_tables", "schema_mapping")
"""Columns added to ``ingestion_import_runs`` after the first release."""


def _now() -> datetime:
    """Returns the current UTC timestamp written by the read model."""
    return datetime.now(UTC)


class SQLAlchemyIngestionView(AsyncSQLAlchemyTrackingRecorder, IngestionView):
    """Asynchronous materialised view of the ingestion aggregates."""

    async def create_table(self) -> None:
        """Creates the tracking table and the view tables if they do not exist."""
        async with self.datastore.transaction() as conn:
            await conn.run_sync(metadata.create_all)
            await conn.run_sync(self.datastore.metadata.create_all)
            await self._ensure_import_run_columns(conn)

    async def _ensure_import_run_columns(self, conn: AsyncConnection) -> None:
        """Adds the filter and mapping columns to an existing import run table."""
        if self.datastore.dialect_name == AsyncSQLAlchemyDatastore.SQLITE:
            result = await conn.exec_driver_sql("PRAGMA table_info(ingestion_import_runs)")
            existing = {str(row._mapping["name"]) for row in result.fetchall()}
            for column in IMPORT_RUN_COLUMNS:
                if column not in existing:
                    await conn.exec_driver_sql(
                        f"ALTER TABLE ingestion_import_runs "
                        f"ADD COLUMN {column} TEXT NOT NULL DEFAULT '{{}}'"
                    )
            return
        for column in IMPORT_RUN_COLUMNS:
            await conn.exec_driver_sql(
                f"ALTER TABLE ingestion_import_runs "
                f"ADD COLUMN IF NOT EXISTS {column} TEXT NOT NULL DEFAULT '{{}}'"
            )

    def _insert(self, table: Table) -> Any:
        """Returns the upsert construct of the configured dialect."""
        if self.datastore.dialect_name == AsyncSQLAlchemyDatastore.SQLITE:
            return sqlite_insert(table)
        return pg_insert(table)

    async def _write(self, statements: Sequence[Any], tracking: Tracking) -> None:
        """Applies the statements and records the tracking row atomically."""
        async with self.transaction() as conn:
            for statement in statements:
                await conn.execute(statement)
            await self.insert_tracking_in_transaction(conn, tracking)

    async def _fetch_all(self, statement: Select[Any]) -> Sequence[Any]:
        """Executes a read statement and returns all rows."""
        async with self.datastore.connection() as conn:
            rows: Sequence[Any] = (await conn.execute(statement)).all()
            return rows

    async def _fetch_one(self, statement: Select[Any]) -> Any:
        """Executes a read statement and returns the first row, or ``None``."""
        async with self.datastore.connection() as conn:
            return (await conn.execute(statement)).first()

    async def register_connection(
        self,
        connection_id: UUID,
        name: str,
        kind: str,
        endpoint: str,
        credential_ref: str | None,
        has_inline_credential: bool,
        default_catalog: str | None,
        options: dict[str, str],
        tracking: Tracking,
    ) -> None:
        """Registers a connection in the view."""
        statement = self._insert(ingestion_connections).values(
            connection_id=connection_id,
            name=name,
            kind=kind,
            endpoint=endpoint,
            credential_ref=credential_ref,
            has_inline_credential=has_inline_credential,
            default_catalog=default_catalog,
            options=json.dumps(options),
            discarded_at=None,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[ingestion_connections.c.connection_id],
            set_={
                "name": statement.excluded.name,
                "kind": statement.excluded.kind,
                "endpoint": statement.excluded.endpoint,
                "credential_ref": statement.excluded.credential_ref,
                "has_inline_credential": statement.excluded.has_inline_credential,
                "default_catalog": statement.excluded.default_catalog,
                "options": statement.excluded.options,
                "discarded_at": statement.excluded.discarded_at,
            },
        )
        await self._write([statement], tracking)

    async def change_connection(
        self,
        connection_id: UUID,
        name: str | None,
        endpoint: str | None,
        default_catalog: str | None,
        options: dict[str, str] | None,
        tracking: Tracking,
    ) -> None:
        """Changes connection metadata, updating only the non-``None`` fields."""
        values: dict[str, Any] = {}
        if name is not None:
            values["name"] = name
        if endpoint is not None:
            values["endpoint"] = endpoint
        if default_catalog is not None:
            values["default_catalog"] = default_catalog
        if options is not None:
            values["options"] = json.dumps(options)
        statements: list[Any] = []
        if values:
            statements.append(
                update(ingestion_connections)
                .where(ingestion_connections.c.connection_id == connection_id)
                .values(**values)
            )
        await self._write(statements, tracking)

    async def rotate_credential(
        self,
        connection_id: UUID,
        credential_ref: str | None,
        has_inline_credential: bool,
        tracking: Tracking,
    ) -> None:
        """Updates the credential pointer of a connection."""
        statement = (
            update(ingestion_connections)
            .where(ingestion_connections.c.connection_id == connection_id)
            .values(
                credential_ref=credential_ref,
                has_inline_credential=has_inline_credential,
            )
        )
        await self._write([statement], tracking)

    async def discard_connection(self, connection_id: UUID, tracking: Tracking) -> None:
        """Marks a connection as discarded."""
        statement = (
            update(ingestion_connections)
            .where(ingestion_connections.c.connection_id == connection_id)
            .values(discarded_at=_now())
        )
        await self._write([statement], tracking)

    async def get_connection(self, connection_id: UUID) -> ConnectionRow | None:
        """Returns the connection with the given id, or ``None``."""
        row = await self._fetch_one(
            select(ingestion_connections).where(
                ingestion_connections.c.connection_id == connection_id,
                ingestion_connections.c.discarded_at.is_(None),
            )
        )
        return None if row is None else self._connection_row(row)

    async def find_connection_by_name(self, name: str) -> ConnectionRow | None:
        """Returns the live connection with the given name, or ``None``."""
        row = await self._fetch_one(
            select(ingestion_connections).where(
                ingestion_connections.c.name == name,
                ingestion_connections.c.discarded_at.is_(None),
            )
        )
        return None if row is None else self._connection_row(row)

    async def list_connections(
        self,
        kind: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[ConnectionRow]:
        """Returns live connections, optionally filtered by kind and paged."""
        statement = select(ingestion_connections).where(
            ingestion_connections.c.discarded_at.is_(None)
        )
        if kind is not None:
            statement = statement.where(ingestion_connections.c.kind == kind)
        statement = statement.order_by(ingestion_connections.c.name)
        if limit is not None:
            statement = statement.limit(limit)
        if offset:
            statement = statement.offset(offset)
        return [self._connection_row(row) for row in await self._fetch_all(statement)]

    async def register_import_run(
        self,
        run_id: UUID,
        connection_id: UUID,
        target_catalog_id: UUID,
        source_catalog: str | None,
        include_schemas: list[str],
        include_tables: dict[str, list[str]],
        schema_mapping: dict[str, str],
        tracking: Tracking,
    ) -> None:
        """Registers a run in the view with status ``pending``."""
        statement = self._insert(ingestion_import_runs).values(
            run_id=run_id,
            connection_id=connection_id,
            target_catalog_id=target_catalog_id,
            source_catalog=source_catalog,
            include_schemas=json.dumps(include_schemas or []),
            include_tables=json.dumps(include_tables or {}),
            schema_mapping=json.dumps(schema_mapping or {}),
            status="pending",
            schema_count=0,
            table_count=0,
            field_count=0,
            error=None,
            created_at=_now(),
        )
        statement = statement.on_conflict_do_update(
            index_elements=[ingestion_import_runs.c.run_id],
            set_={
                "connection_id": statement.excluded.connection_id,
                "target_catalog_id": statement.excluded.target_catalog_id,
                "source_catalog": statement.excluded.source_catalog,
                "include_schemas": statement.excluded.include_schemas,
                "include_tables": statement.excluded.include_tables,
                "schema_mapping": statement.excluded.schema_mapping,
                "status": statement.excluded.status,
                "schema_count": statement.excluded.schema_count,
                "table_count": statement.excluded.table_count,
                "field_count": statement.excluded.field_count,
                "error": statement.excluded.error,
            },
        )
        await self._write([statement], tracking)

    async def finish_import_run(
        self,
        run_id: UUID,
        status: str,
        schema_count: int,
        table_count: int,
        field_count: int,
        error: str | None,
        tracking: Tracking,
    ) -> None:
        """Finalises a run in the view."""
        statement = (
            update(ingestion_import_runs)
            .where(ingestion_import_runs.c.run_id == run_id)
            .values(
                status=status,
                schema_count=schema_count,
                table_count=table_count,
                field_count=field_count,
                error=error,
            )
        )
        await self._write([statement], tracking)

    async def get_import_run(self, run_id: UUID) -> ImportRunRow | None:
        """Returns the run with the given id, or ``None``."""
        row = await self._fetch_one(
            select(ingestion_import_runs).where(ingestion_import_runs.c.run_id == run_id)
        )
        return None if row is None else self._run_row(row)

    async def list_import_runs(
        self,
        connection_id: UUID | None = None,
        status: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[ImportRunRow]:
        """Returns runs, optionally filtered and paged, ordered by creation."""
        statement = select(ingestion_import_runs)
        if connection_id is not None:
            statement = statement.where(ingestion_import_runs.c.connection_id == connection_id)
        if status is not None:
            statement = statement.where(ingestion_import_runs.c.status == status)
        statement = statement.order_by(
            ingestion_import_runs.c.created_at,
            ingestion_import_runs.c.run_id,
        )
        if limit is not None:
            statement = statement.limit(limit)
        if offset:
            statement = statement.offset(offset)
        return [self._run_row(row) for row in await self._fetch_all(statement)]

    @staticmethod
    def _connection_row(row: Any) -> ConnectionRow:
        """Builds a connection row from a database row."""
        return ConnectionRow(
            connection_id=as_uuid(row.connection_id),
            name=row.name,
            kind=row.kind,
            endpoint=row.endpoint,
            credential_ref=row.credential_ref,
            has_inline_credential=bool(row.has_inline_credential),
            default_catalog=row.default_catalog,
            options=json.loads(row.options),
        )

    @staticmethod
    def _run_row(row: Any) -> ImportRunRow:
        """Builds an import run row from a database row."""
        return ImportRunRow(
            run_id=as_uuid(row.run_id),
            connection_id=as_uuid(row.connection_id),
            target_catalog_id=as_uuid(row.target_catalog_id),
            source_catalog=row.source_catalog,
            include_schemas=json.loads(row.include_schemas),
            include_tables=json.loads(row.include_tables),
            schema_mapping=json.loads(row.schema_mapping),
            status=row.status,
            schema_count=int(row.schema_count),
            table_count=int(row.table_count),
            field_count=int(row.field_count),
            error=row.error,
            created_at=row.created_at,
        )
