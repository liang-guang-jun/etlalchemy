"""Asynchronous SQLAlchemy implementation of the catalog read model.

SQLAlchemy Core builds the table definitions and the DML statements; they are
executed on the async engine of
:class:`~eventsourcing.asyncio.sqlalchemy.AsyncSQLAlchemyDatastore`, so the view
change and its tracking record still share one transaction. The same class serves
SQLite (``aiosqlite``) and PostgreSQL (``psycopg``); only the upsert dialect
differs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from eventsourcing.asyncio.sqlalchemy import AsyncSQLAlchemyDatastore
from sqlalchemy import ColumnElement, Select, delete, func, or_, select, update

from etlalchemy.catalog.aggregates.table import field_identity
from etlalchemy.catalog.aggregates.types import DataType
from etlalchemy.catalog.projection.tables import (
    catalog_fields,
    catalog_schemas,
    catalog_tables,
    catalogs,
    metadata,
)
from etlalchemy.catalog.projection.view import (
    CatalogObjectSearchResult,
    CatalogRow,
    CatalogView,
    FieldRow,
    FieldSearchResult,
    SchemaRow,
    TableRow,
    as_uuid,
)
from etlalchemy.shared.persistence import AsyncCoreView, ensure_column, utc_now

if TYPE_CHECKING:
    from eventsourcing.persistence import Tracking


class SQLAlchemyCatalogView(AsyncCoreView, CatalogView):
    """Asynchronous materialised view of the catalog aggregates."""

    view_metadata = metadata

    async def migrate(self, conn: Any) -> None:
        """Adds the columns an older catalog read model predates."""
        await ensure_column(
            conn,
            self.datastore.dialect_name,
            "catalog_tables",
            "description",
            "TEXT NOT NULL DEFAULT ''",
        )
        await ensure_column(
            conn,
            self.datastore.dialect_name,
            "catalog_fields",
            "field_id",
            "TEXT" if self.datastore.dialect_name == AsyncSQLAlchemyDatastore.SQLITE else "UUID",
        )
        await self._backfill_field_ids(conn)
        await ensure_column(
            conn,
            self.datastore.dialect_name,
            "catalog_fields",
            "comment",
            "TEXT NOT NULL DEFAULT ''",
        )

    async def _backfill_field_ids(self, conn: Any) -> None:
        """Gives legacy field rows the derived identity their events replay to.

        The column is added nullable — an ``ALTER`` cannot invent a per-row UUID
        — so every legacy row is filled here, which keeps old and new rows
        agreeing on the same identity.
        """
        rows = (
            await conn.execute(
                select(catalog_fields.c.table_id, catalog_fields.c.name).where(
                    catalog_fields.c.field_id.is_(None)
                )
            )
        ).all()
        for row in rows:
            await conn.execute(
                update(catalog_fields)
                .where(
                    catalog_fields.c.table_id == row.table_id,
                    catalog_fields.c.name == row.name,
                )
                .values(field_id=field_identity(as_uuid(row.table_id), row.name))
            )

    async def register_catalog(
        self,
        catalog_id: UUID,
        name: str,
        description: str,
        tracking: Tracking,
    ) -> None:
        """Registers a catalog in the view."""
        statement = self._dialect_insert(catalogs).values(
            catalog_id=catalog_id,
            name=name,
            description=description,
            discarded_at=None,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[catalogs.c.catalog_id],
            set_={
                "name": statement.excluded.name,
                "description": statement.excluded.description,
                "discarded_at": statement.excluded.discarded_at,
            },
        )
        await self._write([statement], tracking)

    async def change_catalog(
        self,
        catalog_id: UUID,
        name: str | None,
        description: str | None,
        tracking: Tracking,
    ) -> None:
        """Changes a catalog, updating only the non-``None`` attributes."""
        values: dict[str, Any] = {}
        if name is not None:
            values["name"] = name
        if description is not None:
            values["description"] = description
        statements: list[Any] = []
        if values:
            statements.append(
                update(catalogs).where(catalogs.c.catalog_id == catalog_id).values(**values)
            )
        await self._write(statements, tracking)

    async def discard_catalog(self, catalog_id: UUID, tracking: Tracking) -> None:
        """Marks a catalog, its schemas, their tables and fields as discarded."""
        discarded_at = utc_now()
        statements = [
            delete(catalog_fields).where(
                catalog_fields.c.table_id.in_(
                    select(catalog_tables.c.table_id).where(
                        catalog_tables.c.catalog_id == catalog_id
                    )
                )
            ),
            update(catalog_tables)
            .where(
                catalog_tables.c.catalog_id == catalog_id,
                catalog_tables.c.discarded_at.is_(None),
            )
            .values(discarded_at=discarded_at),
            update(catalog_schemas)
            .where(
                catalog_schemas.c.catalog_id == catalog_id,
                catalog_schemas.c.discarded_at.is_(None),
            )
            .values(discarded_at=discarded_at),
            update(catalogs)
            .where(catalogs.c.catalog_id == catalog_id)
            .values(discarded_at=discarded_at),
        ]
        await self._write(statements, tracking)

    async def get_catalog(self, catalog_id: UUID) -> CatalogRow | None:
        """Returns the catalog with the given ID, or ``None``."""
        row = await self._fetch_one(
            select(catalogs).where(
                catalogs.c.catalog_id == catalog_id,
                catalogs.c.discarded_at.is_(None),
            )
        )
        return None if row is None else self._catalog_row(row)

    async def list_catalogs(self) -> list[CatalogRow]:
        """Returns all live catalogs, ordered by name."""
        rows = await self._fetch_all(
            select(catalogs).where(catalogs.c.discarded_at.is_(None)).order_by(catalogs.c.name)
        )
        return [self._catalog_row(row) for row in rows]

    async def register_schema(
        self,
        schema_id: UUID,
        catalog_id: UUID,
        name: str,
        description: str,
        tracking: Tracking,
    ) -> None:
        """Registers a schema in the view."""
        statement = self._dialect_insert(catalog_schemas).values(
            schema_id=schema_id,
            catalog_id=catalog_id,
            name=name,
            description=description,
            discarded_at=None,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[catalog_schemas.c.schema_id],
            set_={
                "catalog_id": statement.excluded.catalog_id,
                "name": statement.excluded.name,
                "description": statement.excluded.description,
                "discarded_at": statement.excluded.discarded_at,
            },
        )
        await self._write([statement], tracking)

    async def unregister_schema(
        self,
        catalog_id: UUID,
        schema_name: str,
        tracking: Tracking,
    ) -> None:
        """Marks a schema and its tables as discarded and drops their fields."""
        schema_ids = select(catalog_schemas.c.schema_id).where(
            catalog_schemas.c.catalog_id == catalog_id,
            catalog_schemas.c.name == schema_name,
            catalog_schemas.c.discarded_at.is_(None),
        )
        await self._discard_schemas(schema_ids, tracking)

    async def change_schema(
        self,
        schema_id: UUID,
        name: str | None,
        description: str | None,
        tracking: Tracking,
    ) -> None:
        """Changes a schema, updating only the non-``None`` attributes."""
        values: dict[str, Any] = {}
        if name is not None:
            values["name"] = name
        if description is not None:
            values["description"] = description
        statements: list[Any] = []
        if values:
            statements.append(
                update(catalog_schemas)
                .where(catalog_schemas.c.schema_id == schema_id)
                .values(**values)
            )
        await self._write(statements, tracking)

    async def discard_schema(self, schema_id: UUID, tracking: Tracking) -> None:
        """Marks a schema and its tables as discarded and drops their fields."""
        schema_ids = select(catalog_schemas.c.schema_id).where(
            catalog_schemas.c.schema_id == schema_id
        )
        await self._discard_schemas(schema_ids, tracking)

    async def _discard_schemas(self, schema_ids: Select[Any], tracking: Tracking) -> None:
        """Discards the schemas selected by ``schema_ids`` and their children."""
        discarded_at = utc_now()
        statements = [
            delete(catalog_fields).where(
                catalog_fields.c.table_id.in_(
                    select(catalog_tables.c.table_id).where(
                        catalog_tables.c.schema_id.in_(schema_ids)
                    )
                )
            ),
            update(catalog_tables)
            .where(
                catalog_tables.c.schema_id.in_(schema_ids),
                catalog_tables.c.discarded_at.is_(None),
            )
            .values(discarded_at=discarded_at),
            update(catalog_schemas)
            .where(
                catalog_schemas.c.schema_id.in_(schema_ids),
                catalog_schemas.c.discarded_at.is_(None),
            )
            .values(discarded_at=discarded_at),
        ]
        await self._write(statements, tracking)

    async def register_table(
        self,
        table_id: UUID,
        schema_id: UUID,
        catalog_id: UUID,
        name: str,
        tracking: Tracking,
        description: str = "",
    ) -> None:
        """Registers a table in the view."""
        statement = self._dialect_insert(catalog_tables).values(
            table_id=table_id,
            schema_id=schema_id,
            catalog_id=catalog_id,
            name=name,
            description=description,
            discarded_at=None,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[catalog_tables.c.table_id],
            set_={
                "schema_id": statement.excluded.schema_id,
                "catalog_id": statement.excluded.catalog_id,
                "name": statement.excluded.name,
                "description": statement.excluded.description,
                "discarded_at": statement.excluded.discarded_at,
            },
        )
        await self._write([statement], tracking)

    async def unregister_table(
        self,
        schema_id: UUID,
        table_name: str,
        tracking: Tracking,
    ) -> None:
        """Marks a table as discarded and drops its fields."""
        table_ids = select(catalog_tables.c.table_id).where(
            catalog_tables.c.schema_id == schema_id,
            catalog_tables.c.name == table_name,
            catalog_tables.c.discarded_at.is_(None),
        )
        await self._discard_tables(table_ids, tracking)

    async def change_table(
        self,
        table_id: UUID,
        name: str | None,
        tracking: Tracking,
        description: str | None = None,
    ) -> None:
        """Changes a table, updating only the non-``None`` attributes."""
        values: dict[str, Any] = {}
        if name is not None:
            values["name"] = name
        if description is not None:
            values["description"] = description
        statements: list[Any] = []
        if values:
            statements.append(
                update(catalog_tables).where(catalog_tables.c.table_id == table_id).values(**values)
            )
        await self._write(statements, tracking)

    async def discard_table(self, table_id: UUID, tracking: Tracking) -> None:
        """Marks a table as discarded and drops its fields."""
        table_ids = select(catalog_tables.c.table_id).where(catalog_tables.c.table_id == table_id)
        await self._discard_tables(table_ids, tracking)

    async def _discard_tables(self, table_ids: Select[Any], tracking: Tracking) -> None:
        """Discards the tables selected by ``table_ids`` and drops their fields."""
        discarded_at = utc_now()
        statements = [
            delete(catalog_fields).where(catalog_fields.c.table_id.in_(table_ids)),
            update(catalog_tables)
            .where(
                catalog_tables.c.table_id.in_(table_ids),
                catalog_tables.c.discarded_at.is_(None),
            )
            .values(discarded_at=discarded_at),
        ]
        await self._write(statements, tracking)

    async def add_field(
        self,
        table_id: UUID,
        name: str,
        data_type: DataType,
        nullable: bool,
        tracking: Tracking,
        field_id: UUID | None = None,
    ) -> None:
        """Adds a field to a table in the view."""
        statement = self._dialect_insert(catalog_fields).values(
            table_id=table_id,
            field_id=field_id or field_identity(table_id, name),
            name=name,
            data_type=str(data_type),
            nullable=nullable,
            comment="",
        )
        statement = statement.on_conflict_do_update(
            index_elements=[catalog_fields.c.table_id, catalog_fields.c.name],
            set_={
                "data_type": statement.excluded.data_type,
                "nullable": statement.excluded.nullable,
                "comment": statement.excluded.comment,
            },
        )
        await self._write([statement], tracking)

    async def remove_field(
        self,
        table_id: UUID,
        name: str,
        tracking: Tracking,
    ) -> None:
        """Removes a field from a table in the view."""
        statement = delete(catalog_fields).where(
            catalog_fields.c.table_id == table_id,
            catalog_fields.c.name == name,
        )
        await self._write([statement], tracking)

    async def change_field(
        self,
        table_id: UUID,
        name: str,
        data_type: DataType | None,
        nullable: bool | None,
        tracking: Tracking,
        comment: str | None = None,
    ) -> None:
        """Changes a field, updating only the non-``None`` attributes."""
        values: dict[str, Any] = {}
        if data_type is not None:
            values["data_type"] = str(data_type)
        if nullable is not None:
            values["nullable"] = nullable
        if comment is not None:
            values["comment"] = comment
        statements: list[Any] = []
        if values:
            statements.append(
                update(catalog_fields)
                .where(
                    catalog_fields.c.table_id == table_id,
                    catalog_fields.c.name == name,
                )
                .values(**values)
            )
        await self._write(statements, tracking)

    async def rename_field(
        self,
        table_id: UUID,
        old_name: str,
        new_name: str,
        tracking: Tracking,
    ) -> None:
        """Moves a field definition to its new name."""
        async with self.transaction() as conn:
            row = (
                await conn.execute(
                    select(
                        catalog_fields.c.field_id,
                        catalog_fields.c.data_type,
                        catalog_fields.c.nullable,
                    ).where(
                        catalog_fields.c.table_id == table_id,
                        catalog_fields.c.name == old_name,
                    )
                )
            ).first()
            if row is not None:
                await conn.execute(
                    delete(catalog_fields).where(
                        catalog_fields.c.table_id == table_id,
                        or_(
                            catalog_fields.c.name == old_name,
                            catalog_fields.c.name == new_name,
                        ),
                    )
                )
                statement = self._dialect_insert(catalog_fields).values(
                    table_id=table_id,
                    field_id=row.field_id,
                    name=new_name,
                    data_type=row.data_type,
                    nullable=bool(row.nullable),
                )
                statement = statement.on_conflict_do_update(
                    index_elements=[catalog_fields.c.table_id, catalog_fields.c.name],
                    set_={
                        "data_type": statement.excluded.data_type,
                        "nullable": statement.excluded.nullable,
                    },
                )
                await conn.execute(statement)
            await self.insert_tracking_in_transaction(conn, tracking)

    async def get_schema(self, schema_id: UUID) -> SchemaRow | None:
        """Returns the schema with the given ID, or ``None``."""
        row = await self._fetch_one(
            select(catalog_schemas).where(
                catalog_schemas.c.schema_id == schema_id,
                catalog_schemas.c.discarded_at.is_(None),
            )
        )
        return None if row is None else self._schema_row(row)

    async def get_table(self, table_id: UUID) -> TableRow | None:
        """Returns the table with the given ID, or ``None``."""
        row = await self._fetch_one(
            select(catalog_tables).where(
                catalog_tables.c.table_id == table_id,
                catalog_tables.c.discarded_at.is_(None),
            )
        )
        return None if row is None else self._table_row(row)

    async def list_schemas(self, catalog_id: UUID) -> list[SchemaRow]:
        """Returns the live schemas of a catalog, ordered by name."""
        rows = await self._fetch_all(
            select(catalog_schemas)
            .where(
                catalog_schemas.c.catalog_id == catalog_id,
                catalog_schemas.c.discarded_at.is_(None),
            )
            .order_by(catalog_schemas.c.name)
        )
        return [self._schema_row(row) for row in rows]

    async def list_tables(self, schema_id: UUID) -> list[TableRow]:
        """Returns the live tables of a schema, ordered by name."""
        rows = await self._fetch_all(
            select(catalog_tables)
            .where(
                catalog_tables.c.schema_id == schema_id,
                catalog_tables.c.discarded_at.is_(None),
            )
            .order_by(catalog_tables.c.name)
        )
        return [self._table_row(row) for row in rows]

    async def list_fields(self, table_id: UUID) -> list[FieldRow]:
        """Returns the fields of a table, ordered by name."""
        rows = await self._fetch_all(
            select(catalog_fields)
            .where(catalog_fields.c.table_id == table_id)
            .order_by(catalog_fields.c.name)
        )
        return [self._field_row(row) for row in rows]

    async def get_field(self, field_id: UUID) -> FieldRow | None:
        """Returns one live field, or ``None`` for an unknown id."""
        row = await self._fetch_one(
            select(catalog_fields).where(catalog_fields.c.field_id == field_id)
        )
        if row is None:
            return None
        return self._field_row(row)

    async def find_schema_id(self, catalog_id: UUID, name: str) -> UUID | None:
        """Returns the schema ID for a name in a catalog, or ``None``."""
        row = await self._fetch_one(
            select(catalog_schemas.c.schema_id).where(
                catalog_schemas.c.catalog_id == catalog_id,
                catalog_schemas.c.name == name,
                catalog_schemas.c.discarded_at.is_(None),
            )
        )
        return None if row is None else as_uuid(row.schema_id)

    async def find_table_id(self, schema_id: UUID, name: str) -> UUID | None:
        """Returns the table ID for a name in a schema, or ``None``."""
        row = await self._fetch_one(
            select(catalog_tables.c.table_id).where(
                catalog_tables.c.schema_id == schema_id,
                catalog_tables.c.name == name,
                catalog_tables.c.discarded_at.is_(None),
            )
        )
        return None if row is None else as_uuid(row.table_id)

    async def search_fields(
        self,
        term: str,
        catalog_id: UUID | None = None,
    ) -> list[FieldSearchResult]:
        """Finds fields whose schema, table or field name contains ``term``."""
        pattern = f"%{term}%"
        statement = (
            select(
                catalog_schemas.c.catalog_id,
                catalog_schemas.c.schema_id,
                catalog_schemas.c.name.label("schema_name"),
                catalog_tables.c.table_id,
                catalog_tables.c.name.label("table_name"),
                catalog_fields.c.name.label("field_name"),
                catalog_fields.c.data_type,
                catalog_fields.c.nullable,
            )
            .select_from(
                catalog_fields.join(
                    catalog_tables,
                    catalog_tables.c.table_id == catalog_fields.c.table_id,
                ).join(
                    catalog_schemas,
                    catalog_schemas.c.schema_id == catalog_tables.c.schema_id,
                )
            )
            .where(
                or_(
                    catalog_schemas.c.name.like(pattern),
                    catalog_tables.c.name.like(pattern),
                    catalog_fields.c.name.like(pattern),
                ),
                catalog_schemas.c.discarded_at.is_(None),
                catalog_tables.c.discarded_at.is_(None),
            )
        )
        if catalog_id is not None:
            statement = statement.where(catalog_schemas.c.catalog_id == catalog_id)
        statement = statement.order_by(
            catalog_schemas.c.name,
            catalog_tables.c.name,
            catalog_fields.c.name,
        )
        return [self._search_row(row) for row in await self._fetch_all(statement)]

    async def search_objects(
        self,
        term: str,
        catalog_id: UUID | None = None,
        limit: int = 20,
    ) -> list[CatalogObjectSearchResult]:
        """Finds catalogs, schemas, tables and fields whose own name matches ``term``."""
        pattern = f"%{term.lower()}%"
        results: list[CatalogObjectSearchResult] = []

        catalog_filters: list[ColumnElement[bool]] = [
            func.lower(catalogs.c.name).like(pattern),
            catalogs.c.discarded_at.is_(None),
        ]
        if catalog_id is not None:
            catalog_filters.append(catalogs.c.catalog_id == catalog_id)
        catalog_statement = (
            select(catalogs.c.catalog_id, catalogs.c.name)
            .where(*catalog_filters)
            .order_by(catalogs.c.name)
            .limit(limit)
        )
        for row in await self._fetch_all(catalog_statement):
            name = str(row.name)
            results.append(
                CatalogObjectSearchResult(
                    kind="catalog",
                    target_id=as_uuid(row.catalog_id),
                    field_name="",
                    name=name,
                    path=name,
                )
            )

        schema_filters: list[ColumnElement[bool]] = [
            func.lower(catalog_schemas.c.name).like(pattern),
            catalog_schemas.c.discarded_at.is_(None),
            catalogs.c.discarded_at.is_(None),
        ]
        if catalog_id is not None:
            schema_filters.append(catalog_schemas.c.catalog_id == catalog_id)
        schema_statement = (
            select(
                catalog_schemas.c.schema_id,
                catalog_schemas.c.name.label("object_name"),
                catalogs.c.name.label("catalog_name"),
            )
            .select_from(
                catalog_schemas.join(
                    catalogs,
                    catalogs.c.catalog_id == catalog_schemas.c.catalog_id,
                )
            )
            .where(*schema_filters)
            .order_by(catalogs.c.name, catalog_schemas.c.name)
            .limit(limit)
        )
        for row in await self._fetch_all(schema_statement):
            name = str(row.object_name)
            results.append(
                CatalogObjectSearchResult(
                    kind="schema",
                    target_id=as_uuid(row.schema_id),
                    field_name="",
                    name=name,
                    path=f"{row.catalog_name} / {name}",
                )
            )

        table_filters: list[ColumnElement[bool]] = [
            func.lower(catalog_tables.c.name).like(pattern),
            catalog_tables.c.discarded_at.is_(None),
            catalog_schemas.c.discarded_at.is_(None),
            catalogs.c.discarded_at.is_(None),
        ]
        if catalog_id is not None:
            table_filters.append(catalog_tables.c.catalog_id == catalog_id)
        table_statement = (
            select(
                catalog_tables.c.table_id,
                catalog_tables.c.name.label("object_name"),
                catalog_schemas.c.name.label("schema_name"),
                catalogs.c.name.label("catalog_name"),
            )
            .select_from(
                catalog_tables.join(
                    catalog_schemas,
                    catalog_schemas.c.schema_id == catalog_tables.c.schema_id,
                ).join(
                    catalogs,
                    catalogs.c.catalog_id == catalog_schemas.c.catalog_id,
                )
            )
            .where(*table_filters)
            .order_by(catalogs.c.name, catalog_schemas.c.name, catalog_tables.c.name)
            .limit(limit)
        )
        for row in await self._fetch_all(table_statement):
            name = str(row.object_name)
            results.append(
                CatalogObjectSearchResult(
                    kind="table",
                    target_id=as_uuid(row.table_id),
                    field_name="",
                    name=name,
                    path=f"{row.catalog_name} / {row.schema_name} / {name}",
                )
            )

        field_filters: list[ColumnElement[bool]] = [
            func.lower(catalog_fields.c.name).like(pattern),
            catalog_tables.c.discarded_at.is_(None),
            catalog_schemas.c.discarded_at.is_(None),
            catalogs.c.discarded_at.is_(None),
        ]
        if catalog_id is not None:
            field_filters.append(catalog_tables.c.catalog_id == catalog_id)
        field_statement = (
            select(
                catalog_tables.c.table_id,
                catalog_fields.c.name.label("object_name"),
                catalog_fields.c.data_type,
                catalog_tables.c.name.label("table_name"),
                catalog_schemas.c.name.label("schema_name"),
                catalogs.c.name.label("catalog_name"),
            )
            .select_from(
                catalog_fields.join(
                    catalog_tables,
                    catalog_tables.c.table_id == catalog_fields.c.table_id,
                )
                .join(
                    catalog_schemas,
                    catalog_schemas.c.schema_id == catalog_tables.c.schema_id,
                )
                .join(
                    catalogs,
                    catalogs.c.catalog_id == catalog_schemas.c.catalog_id,
                )
            )
            .where(*field_filters)
            .order_by(
                catalogs.c.name,
                catalog_schemas.c.name,
                catalog_tables.c.name,
                catalog_fields.c.name,
            )
            .limit(limit)
        )
        for row in await self._fetch_all(field_statement):
            name = str(row.object_name)
            results.append(
                CatalogObjectSearchResult(
                    kind="field",
                    target_id=as_uuid(row.table_id),
                    field_name=name,
                    name=name,
                    path=f"{row.catalog_name} / {row.schema_name} / {row.table_name} / {name}",
                    data_type=str(row.data_type),
                )
            )

        return results

    @staticmethod
    def _catalog_row(row: Any) -> CatalogRow:
        """Builds a catalog row from a database row."""
        return CatalogRow(
            catalog_id=as_uuid(row.catalog_id),
            name=row.name,
            description=row.description,
        )

    @staticmethod
    def _schema_row(row: Any) -> SchemaRow:
        """Builds a schema row from a database row."""
        return SchemaRow(
            schema_id=as_uuid(row.schema_id),
            catalog_id=as_uuid(row.catalog_id),
            name=row.name,
            description=row.description,
        )

    @staticmethod
    def _table_row(row: Any) -> TableRow:
        """Builds a table row from a database row."""
        return TableRow(
            table_id=as_uuid(row.table_id),
            schema_id=as_uuid(row.schema_id),
            catalog_id=as_uuid(row.catalog_id),
            name=row.name,
            description=str(row.description or ""),
        )

    @staticmethod
    def _field_row(row: Any) -> FieldRow:
        """Builds a field row from a database row."""
        return FieldRow(
            table_id=as_uuid(row.table_id),
            field_id=as_uuid(row.field_id),
            name=row.name,
            data_type=DataType.parse(row.data_type),
            nullable=bool(row.nullable),
            comment=str(row.comment or ""),
        )

    @staticmethod
    def _search_row(row: Any) -> FieldSearchResult:
        """Builds a search result from a joined database row."""
        return FieldSearchResult(
            catalog_id=as_uuid(row.catalog_id),
            schema_id=as_uuid(row.schema_id),
            schema_name=row.schema_name,
            table_id=as_uuid(row.table_id),
            table_name=row.table_name,
            field_name=row.field_name,
            data_type=DataType.parse(row.data_type),
            nullable=bool(row.nullable),
        )
