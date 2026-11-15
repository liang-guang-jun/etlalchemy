"""Application service exposing the catalog use cases."""

from __future__ import annotations

from uuid import UUID, uuid4

import structlog
from eventsourcing.asyncio.application import AsyncApplication
from eventsourcing.persistence import JSONTranscoder, Transcoding
from eventsourcing.utils import EnvType

from etlalchemy.catalog.aggregates.catalog import Catalog
from etlalchemy.catalog.aggregates.errors import UnknownSchemaError, UnknownTableError
from etlalchemy.catalog.aggregates.schema import Schema
from etlalchemy.catalog.aggregates.table import Table
from etlalchemy.catalog.aggregates.types import DataType
from etlalchemy.shared.logging import get_logger


def _parse_uuid(value: UUID | str) -> UUID | None:
    """Returns the value as a :class:`UUID`, or ``None`` when it is not one."""
    if isinstance(value, UUID):
        return value
    try:
        return UUID(value)
    except ValueError:
        return None


class DataTypeAsStr(Transcoding):
    """Transcoding that stores a :class:`DataType` as its canonical text."""

    type = DataType
    name = "etlalchemy_data_type"

    def encode(self, obj: DataType) -> str:
        """Encodes the data type as its canonical text form."""
        return str(obj)

    def decode(self, data: str) -> DataType:
        """Decodes canonical text back into a :class:`DataType`."""
        return DataType.parse(data)


class CatalogApplication(AsyncApplication[UUID]):
    """Application service for the catalog context.

    Each use case loads the aggregates it needs through the catalog path
    (catalog -> schema -> table), applies one command per aggregate and saves
    the resulting events in a single unit of work.

    A schema is addressed by the name the catalog registers it under or by its
    id, and a table by the name its schema registers it under or by its id. The
    ids the create use cases return therefore keep working after a rename.
    """

    name = "catalog_application"
    """Application name; the eventsourcing factories derive table names from it."""

    def __init__(self, env: EnvType | None = None) -> None:
        """Creates the application and its structured logger."""
        super().__init__(env=env)
        self._log: structlog.stdlib.BoundLogger = get_logger("catalog.application")

    def register_transcodings(self, transcoder: JSONTranscoder) -> None:
        """Registers the catalog-specific value object transcodings."""
        super().register_transcodings(transcoder)
        transcoder.register(DataTypeAsStr())

    async def create_catalog(self, name: str, description: str = "") -> UUID:
        """Creates a catalog and returns its ID."""
        self._log.info("catalog.create start", name=name)
        catalog = Catalog(name=name, description=description)
        await self.save(catalog)
        self._log.info("catalog.create done", catalog_id=str(catalog.id))
        return catalog.id

    async def get_catalog(self, catalog_id: UUID) -> Catalog:
        """Returns the catalog with the given ID."""
        self._log.debug("catalog.get start", catalog_id=str(catalog_id))
        catalog: Catalog = await self.repository.get(catalog_id)
        assert isinstance(catalog, Catalog)
        self._log.debug("catalog.get done", catalog_id=str(catalog.id), name=catalog.name)
        return catalog

    async def change_catalog(
        self,
        catalog_id: UUID,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        """Changes the name and/or description of a catalog."""
        self._log.info(
            "catalog.change start",
            catalog_id=str(catalog_id),
            name=name,
            changes_description=description is not None,
        )
        catalog = await self.get_catalog(catalog_id)
        catalog.change(name, description)
        await self.save(catalog)
        self._log.info("catalog.change done", catalog_id=str(catalog_id))

    async def discard_catalog(self, catalog_id: UUID) -> None:
        """Marks a catalog as discarded."""
        self._log.info("catalog.discard start", catalog_id=str(catalog_id))
        catalog = await self.get_catalog(catalog_id)
        catalog.discard()
        await self.save(catalog)
        self._log.info("catalog.discard done", catalog_id=str(catalog_id))

    async def create_schema(
        self,
        catalog_id: UUID,
        schema_name: str,
        description: str = "",
    ) -> UUID:
        """Creates a schema, registers it in the catalog and returns its ID."""
        self._log.info(
            "catalog.schema.create start",
            catalog_id=str(catalog_id),
            schema=schema_name,
        )
        catalog = await self.get_catalog(catalog_id)
        schema = Schema(catalog_id=catalog_id, name=schema_name, description=description)
        catalog.register_schema(schema_name, schema.id, description)
        await self.save(catalog, schema)
        self._log.info("catalog.schema.create done", schema_id=str(schema.id))
        return schema.id

    async def get_schema(self, catalog_id: UUID, schema: UUID | str) -> Schema:
        """Returns the schema referenced by its name or id in the catalog."""
        self._log.debug("catalog.schema.get start", catalog_id=str(catalog_id), schema=str(schema))
        loaded = await self._schema(await self.get_catalog(catalog_id), schema)
        self._log.debug("catalog.schema.get done", schema_id=str(loaded.id), name=loaded.name)
        return loaded

    async def change_schema(
        self,
        catalog_id: UUID,
        schema: UUID | str,
        new_name: str | None = None,
        new_description: str | None = None,
    ) -> None:
        """Changes a schema and keeps the catalog registry in step."""
        self._log.info(
            "catalog.schema.change start",
            catalog_id=str(catalog_id),
            schema=str(schema),
            new_name=new_name,
        )
        catalog = await self.get_catalog(catalog_id)
        loaded = await self._schema(catalog, schema)
        loaded.change(new_name, new_description)
        if new_name is not None:
            catalog.rename_schema(loaded.id, new_name)
        await self.save(catalog, loaded)
        self._log.info("catalog.schema.change done", schema_id=str(loaded.id))

    async def discard_schema(self, catalog_id: UUID, schema: UUID | str) -> None:
        """Unregisters a schema from the catalog and discards it."""
        self._log.info(
            "catalog.schema.discard start",
            catalog_id=str(catalog_id),
            schema=str(schema),
        )
        catalog = await self.get_catalog(catalog_id)
        loaded = await self._schema(catalog, schema)
        catalog.unregister_schema(loaded.name)
        loaded.discard()
        await self.save(catalog, loaded)
        self._log.info("catalog.schema.discard done", schema_id=str(loaded.id))

    async def remove_schema(self, catalog_id: UUID, schema: UUID | str) -> None:
        """Unregisters a schema from the catalog."""
        self._log.info(
            "catalog.schema.remove start",
            catalog_id=str(catalog_id),
            schema=str(schema),
        )
        catalog = await self.get_catalog(catalog_id)
        loaded = await self._schema(catalog, schema)
        catalog.unregister_schema(loaded.name)
        await self.save(catalog)
        self._log.info("catalog.schema.remove done", schema_id=str(loaded.id))

    async def add_table(self, catalog_id: UUID, schema: UUID | str, table_name: str) -> UUID:
        """Creates a table, registers it in the schema and returns its ID."""
        self._log.info(
            "catalog.table.add start",
            catalog_id=str(catalog_id),
            schema=str(schema),
            table=table_name,
        )
        loaded = await self.get_schema(catalog_id, schema)
        table = Table(schema_id=loaded.id, name=table_name)
        loaded.register_table(table_name, table.id)
        await self.save(loaded, table)
        self._log.info("catalog.table.add done", table_id=str(table.id))
        return table.id

    async def get_table(self, catalog_id: UUID, schema: UUID | str, table: UUID | str) -> Table:
        """Returns the table referenced by its name or id in the schema."""
        self._log.debug(
            "catalog.table.get start",
            catalog_id=str(catalog_id),
            schema=str(schema),
            table=str(table),
        )
        loaded = await self._table(await self.get_schema(catalog_id, schema), table)
        self._log.debug("catalog.table.get done", table_id=str(loaded.id), name=loaded.name)
        return loaded

    async def change_table(
        self,
        catalog_id: UUID,
        schema: UUID | str,
        table: UUID | str,
        new_name: str | None = None,
        new_description: str | None = None,
    ) -> None:
        """Changes a table and keeps the schema registry in step."""
        self._log.info(
            "catalog.table.change start",
            catalog_id=str(catalog_id),
            schema=str(schema),
            table=str(table),
            new_name=new_name,
            changes_description=new_description is not None,
        )
        loaded_schema = await self.get_schema(catalog_id, schema)
        loaded_table = await self._table(loaded_schema, table)
        loaded_table.change(new_name, new_description)
        if new_name is not None:
            loaded_schema.rename_table(loaded_table.id, new_name)
        await self.save(loaded_schema, loaded_table)
        self._log.info("catalog.table.change done", table_id=str(loaded_table.id))

    async def discard_table(
        self,
        catalog_id: UUID,
        schema: UUID | str,
        table: UUID | str,
    ) -> None:
        """Unregisters a table from the schema and discards it."""
        self._log.info(
            "catalog.table.discard start",
            catalog_id=str(catalog_id),
            schema=str(schema),
            table=str(table),
        )
        loaded_schema = await self.get_schema(catalog_id, schema)
        loaded_table = await self._table(loaded_schema, table)
        loaded_schema.unregister_table(loaded_table.name)
        loaded_table.discard()
        await self.save(loaded_schema, loaded_table)
        self._log.info("catalog.table.discard done", table_id=str(loaded_table.id))

    async def remove_table(
        self,
        catalog_id: UUID,
        schema: UUID | str,
        table: UUID | str,
    ) -> None:
        """Unregisters a table from the schema."""
        self._log.info(
            "catalog.table.remove start",
            catalog_id=str(catalog_id),
            schema=str(schema),
            table=str(table),
        )
        loaded_schema = await self.get_schema(catalog_id, schema)
        loaded_table = await self._table(loaded_schema, table)
        loaded_schema.unregister_table(loaded_table.name)
        await self.save(loaded_schema)
        self._log.info("catalog.table.remove done", table_id=str(loaded_table.id))

    async def add_field(
        self,
        catalog_id: UUID,
        schema: UUID | str,
        table: UUID | str,
        field_name: str,
        data_type: str | DataType,
        nullable: bool = True,
    ) -> None:
        """Adds a field to the table referenced by its name or id."""
        self._log.info(
            "catalog.field.add start",
            catalog_id=str(catalog_id),
            schema=str(schema),
            table=str(table),
            field=field_name,
            data_type=str(data_type),
            nullable=nullable,
        )
        loaded = await self.get_table(catalog_id, schema, table)
        loaded.add_field(field_name, DataType.parse(data_type), nullable, uuid4())
        await self.save(loaded)
        self._log.info("catalog.field.add done", field=field_name)

    async def remove_field(
        self,
        catalog_id: UUID,
        schema: UUID | str,
        table: UUID | str,
        field_name: str,
    ) -> None:
        """Removes a field from the table referenced by its name or id."""
        self._log.info(
            "catalog.field.remove start",
            catalog_id=str(catalog_id),
            schema=str(schema),
            table=str(table),
            field=field_name,
        )
        loaded = await self.get_table(catalog_id, schema, table)
        loaded.remove_field(field_name)
        await self.save(loaded)
        self._log.info("catalog.field.remove done", field=field_name)

    async def change_field(
        self,
        catalog_id: UUID,
        schema: UUID | str,
        table: UUID | str,
        field_name: str,
        data_type: str | DataType | None = None,
        nullable: bool | None = None,
    ) -> None:
        """Changes the data type and/or nullability of a field of the table."""
        self._log.info(
            "catalog.field.change start",
            catalog_id=str(catalog_id),
            schema=str(schema),
            table=str(table),
            field=field_name,
            data_type=None if data_type is None else str(data_type),
            nullable=nullable,
        )
        loaded = await self.get_table(catalog_id, schema, table)
        parsed = None if data_type is None else DataType.parse(data_type)
        loaded.change_field(field_name, parsed, nullable)
        await self.save(loaded)
        self._log.info("catalog.field.change done", field=field_name)

    async def rename_field(
        self,
        catalog_id: UUID,
        schema: UUID | str,
        table: UUID | str,
        old_name: str,
        new_name: str,
    ) -> None:
        """Renames a field of the table referenced by its name or id."""
        self._log.info(
            "catalog.field.rename start",
            catalog_id=str(catalog_id),
            schema=str(schema),
            table=str(table),
            field=old_name,
            new_name=new_name,
        )
        loaded = await self.get_table(catalog_id, schema, table)
        loaded.rename_field(old_name, new_name)
        await self.save(loaded)
        self._log.info("catalog.field.rename done", field=new_name)

    async def change_field_comment(
        self,
        catalog_id: UUID,
        schema: UUID | str,
        table: UUID | str,
        field_name: str,
        comment: str,
    ) -> None:
        """Documents a field of the table with a free-form comment."""
        self._log.info(
            "catalog.field.comment start",
            catalog_id=str(catalog_id),
            schema=str(schema),
            table=str(table),
            field=field_name,
        )
        loaded = await self.get_table(catalog_id, schema, table)
        loaded.change_field_comment(field_name, comment)
        await self.save(loaded)
        self._log.info("catalog.field.comment done", field=field_name)

    async def _schema(self, catalog: Catalog, schema: UUID | str) -> Schema:
        """Loads the schema referenced by its name or id in the catalog."""
        registered = catalog.schemas.get(schema) if isinstance(schema, str) else None
        schema_id = registered if registered is not None else _parse_uuid(schema)
        if schema_id is None or schema_id not in catalog.schemas.values():
            self._log.debug(
                "catalog.schema.not_found",
                catalog_id=str(catalog.id),
                schema=str(schema),
            )
            msg = f"Schema {schema!r} does not exist in catalog {catalog.name!r}"
            raise UnknownSchemaError(msg)
        loaded: Schema = await self.repository.get(schema_id)
        assert isinstance(loaded, Schema)
        return loaded

    async def _table(self, schema: Schema, table: UUID | str) -> Table:
        """Loads the table referenced by its name or id in the schema."""
        registered = schema.tables.get(table) if isinstance(table, str) else None
        table_id = registered if registered is not None else _parse_uuid(table)
        if table_id is None or table_id not in schema.tables.values():
            self._log.debug(
                "catalog.table.not_found",
                schema_id=str(schema.id),
                table=str(table),
            )
            msg = f"Table {table!r} does not exist in schema {schema.name!r}"
            raise UnknownTableError(msg)
        loaded: Table = await self.repository.get(table_id)
        assert isinstance(loaded, Table)
        return loaded
