"""Read model interface for the catalog context."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import UUID

from eventsourcing.persistence import Tracking

from etlalchemy._vendor.eventsourcing.asyncio.persistence import AsyncTrackingRecorder
from etlalchemy.catalog.aggregates.types import DataType


def as_uuid(value: UUID | str) -> UUID:
    """Returns the given value as a :class:`UUID`."""
    return value if isinstance(value, UUID) else UUID(value)


@dataclass(frozen=True)
class CatalogRow:
    """A catalog as stored in the catalog read model."""

    catalog_id: UUID
    """ID of the catalog aggregate."""
    name: str
    """Name of the catalog."""
    description: str
    """Free-form description of the catalog."""


@dataclass(frozen=True)
class SchemaRow:
    """A schema as stored in the catalog read model."""

    schema_id: UUID
    """ID of the schema aggregate."""
    catalog_id: UUID
    """ID of the catalog that owns the schema."""
    name: str
    """Name the schema is registered under."""
    description: str
    """Free-form description of the schema."""


@dataclass(frozen=True)
class TableRow:
    """A table as stored in the catalog read model."""

    table_id: UUID
    """ID of the table aggregate."""
    schema_id: UUID
    """ID of the schema that owns the table."""
    catalog_id: UUID
    """ID of the catalog that owns the schema."""
    name: str
    """Name the table is registered under."""
    description: str = ""
    """Free-form description of the table."""


@dataclass(frozen=True)
class FieldRow:
    """A field as stored in the catalog read model."""

    table_id: UUID
    """ID of the table that owns the field."""
    field_id: UUID
    """Identity of the field, used to address it on its own."""
    name: str
    """Name of the field."""
    data_type: DataType
    """Normalised data type of the field."""
    nullable: bool
    """Whether the field may hold null values."""
    comment: str = ""
    """Free-form comment that documents the field."""


@dataclass(frozen=True)
class FieldSearchResult:
    """A field found by a cross-aggregate search."""

    catalog_id: UUID
    """ID of the catalog that owns the schema."""
    schema_id: UUID
    """ID of the schema that owns the table."""
    schema_name: str
    """Name of the schema that owns the table."""
    table_id: UUID
    """ID of the table that owns the field."""
    table_name: str
    """Name of the table that owns the field."""
    field_name: str
    """Name of the field."""
    data_type: DataType
    """Normalised data type of the field."""
    nullable: bool
    """Whether the field may hold null values."""


@dataclass(frozen=True)
class CatalogObjectSearchResult:
    """A catalog object found by a cross-level name search."""

    kind: str
    """One of ``catalog``, ``schema``, ``table`` or ``field``."""
    target_id: UUID
    """ID of the catalog, schema or table, or of the owning table for a field."""
    field_name: str
    """Name of the field for ``field`` results, empty otherwise."""
    name: str
    """Name of the object itself."""
    path: str
    """Slash separated path such as ``analytics / sales / orders / id``."""
    data_type: str = ""
    """Canonical data type for ``field`` results, empty otherwise."""


class CatalogView(AsyncTrackingRecorder, ABC):
    """Materialised view of the catalog aggregates.

    Every command method receives the :class:`Tracking` object of the event it
    applies and must write the view change and the tracking record in the same
    database transaction, so that replaying an already applied notification
    rolls back instead of corrupting the view.
    """

    @abstractmethod
    async def create_table(self) -> None:
        """Creates the view tables and the tracking table if they do not exist."""
        ...

    @abstractmethod
    async def register_catalog(
        self,
        catalog_id: UUID,
        name: str,
        description: str,
        tracking: Tracking,
    ) -> None:
        """Registers a catalog in the view."""
        ...

    @abstractmethod
    async def get_catalog(self, catalog_id: UUID) -> CatalogRow | None:
        """Returns the catalog with the given ID, or ``None``."""
        ...

    @abstractmethod
    async def change_catalog(
        self,
        catalog_id: UUID,
        name: str | None,
        description: str | None,
        tracking: Tracking,
    ) -> None:
        """Changes a catalog, updating only the non-``None`` attributes."""
        ...

    @abstractmethod
    async def discard_catalog(self, catalog_id: UUID, tracking: Tracking) -> None:
        """Marks a catalog, its schemas, their tables and fields as discarded."""
        ...

    @abstractmethod
    async def list_catalogs(self) -> list[CatalogRow]:
        """Returns all catalogs, ordered by name."""
        ...

    @abstractmethod
    async def register_schema(
        self,
        schema_id: UUID,
        catalog_id: UUID,
        name: str,
        description: str,
        tracking: Tracking,
    ) -> None:
        """Registers a schema in the view."""
        ...

    @abstractmethod
    async def unregister_schema(
        self,
        catalog_id: UUID,
        schema_name: str,
        tracking: Tracking,
    ) -> None:
        """Marks a schema and its tables as discarded and drops their fields."""
        ...

    @abstractmethod
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
        ...

    @abstractmethod
    async def unregister_table(
        self,
        schema_id: UUID,
        table_name: str,
        tracking: Tracking,
    ) -> None:
        """Marks a table as discarded and drops its fields."""
        ...

    @abstractmethod
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
        ...

    @abstractmethod
    async def remove_field(
        self,
        table_id: UUID,
        name: str,
        tracking: Tracking,
    ) -> None:
        """Removes a field from a table in the view."""
        ...

    @abstractmethod
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
        ...

    @abstractmethod
    async def get_schema(self, schema_id: UUID) -> SchemaRow | None:
        """Returns the schema with the given ID, or ``None``."""
        ...

    @abstractmethod
    async def change_schema(
        self,
        schema_id: UUID,
        name: str | None,
        description: str | None,
        tracking: Tracking,
    ) -> None:
        """Changes a schema, updating only the non-``None`` attributes."""
        ...

    @abstractmethod
    async def discard_schema(self, schema_id: UUID, tracking: Tracking) -> None:
        """Marks a schema and its tables as discarded and drops their fields."""
        ...

    @abstractmethod
    async def get_table(self, table_id: UUID) -> TableRow | None:
        """Returns the table with the given ID, or ``None``."""
        ...

    @abstractmethod
    async def change_table(
        self,
        table_id: UUID,
        name: str | None,
        tracking: Tracking,
        description: str | None = None,
    ) -> None:
        """Changes a table, updating only the non-``None`` attributes."""
        ...

    @abstractmethod
    async def discard_table(self, table_id: UUID, tracking: Tracking) -> None:
        """Marks a table as discarded and drops its fields."""
        ...

    @abstractmethod
    async def rename_field(
        self,
        table_id: UUID,
        old_name: str,
        new_name: str,
        tracking: Tracking,
    ) -> None:
        """Moves a field definition to its new name."""
        ...

    @abstractmethod
    async def list_schemas(self, catalog_id: UUID) -> list[SchemaRow]:
        """Returns the schemas of a catalog, ordered by name."""
        ...

    @abstractmethod
    async def list_tables(self, schema_id: UUID) -> list[TableRow]:
        """Returns the tables of a schema, ordered by name."""
        ...

    @abstractmethod
    async def list_fields(self, table_id: UUID) -> list[FieldRow]:
        """Returns the fields of a table, ordered by name."""
        ...

    @abstractmethod
    async def get_field(self, field_id: UUID) -> FieldRow | None:
        """Returns one live field, or ``None`` for an unknown id."""
        ...

    @abstractmethod
    async def find_schema_id(self, catalog_id: UUID, name: str) -> UUID | None:
        """Returns the schema ID for a name in a catalog, or ``None``."""
        ...

    @abstractmethod
    async def find_table_id(self, schema_id: UUID, name: str) -> UUID | None:
        """Returns the table ID for a name in a schema, or ``None``."""
        ...

    @abstractmethod
    async def search_fields(
        self,
        term: str,
        catalog_id: UUID | None = None,
    ) -> list[FieldSearchResult]:
        """Finds fields whose schema, table or field name contains ``term``."""
        ...

    @abstractmethod
    async def search_objects(
        self,
        term: str,
        catalog_id: UUID | None = None,
        limit: int = 20,
    ) -> list[CatalogObjectSearchResult]:
        """Finds catalogs, schemas, tables and fields whose own name contains ``term``.

        Every level is queried, so a name typed at any depth still resolves into a
        linkable object; ``limit`` caps the hits per level, not the total.
        """
        ...
