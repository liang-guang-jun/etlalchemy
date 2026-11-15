"""Response models of the catalog context."""

from __future__ import annotations

from typing import Self
from uuid import UUID

from pydantic import BaseModel

from etlalchemy.catalog.projection.view import (
    CatalogObjectSearchResult,
    FieldRow,
    FieldSearchResult,
)


class FieldResponse(BaseModel):
    """A field as exposed by the delivery layers."""

    table_id: UUID
    """ID of the table that owns the field."""
    field_id: UUID
    """Identity of the field, stable across renames."""
    name: str
    """Name of the field."""
    data_type: str
    """Canonical data type of the field."""
    nullable: bool
    """Whether the field may hold null values."""
    comment: str = ""
    """Free-form comment that documents the field."""

    @classmethod
    def from_row(cls, row: FieldRow) -> Self:
        """Builds the model from a read model row."""
        return cls(
            table_id=row.table_id,
            field_id=row.field_id,
            name=row.name,
            data_type=str(row.data_type),
            nullable=row.nullable,
            comment=row.comment,
        )


class TableLocationResponse(BaseModel):
    """A table plus the names of the schema and catalog that own it.

    Other contexts only store a table id; this answers everything a link to the
    table detail page needs.
    """

    table_id: UUID
    """ID of the table."""
    name: str
    """Name the table is registered under."""
    catalog_id: UUID
    """ID of the catalog that owns the table."""
    schema_id: UUID
    """ID of the schema that owns the table."""
    schema_name: str
    """Name the schema is registered under."""


class FieldSearchResultResponse(BaseModel):
    """One field found by a cross-aggregate search."""

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
    data_type: str
    """Canonical data type of the field."""
    nullable: bool
    """Whether the field may hold null values."""

    @classmethod
    def from_row(cls, row: FieldSearchResult) -> Self:
        """Builds the model from a read model search result."""
        return cls(
            catalog_id=row.catalog_id,
            schema_id=row.schema_id,
            schema_name=row.schema_name,
            table_id=row.table_id,
            table_name=row.table_name,
            field_name=row.field_name,
            data_type=str(row.data_type),
            nullable=row.nullable,
        )


class CatalogObjectSearchResponse(BaseModel):
    """One catalog object found by a cross-level search."""

    kind: str
    """One of ``catalog``, ``schema``, ``table`` or ``field``."""
    target_id: UUID
    """ID of the catalog, schema or table, or of the owning table for a field."""
    field_name: str
    """Name of the field for ``field`` results, empty otherwise."""
    name: str
    """Name of the object itself."""
    path: str
    """Slash separated path from the catalog down to the object."""
    data_type: str
    """Canonical data type for ``field`` results, empty otherwise."""

    @classmethod
    def from_row(cls, row: CatalogObjectSearchResult) -> Self:
        """Builds the model from a read model search result."""
        return cls(
            kind=row.kind,
            target_id=row.target_id,
            field_name=row.field_name,
            name=row.name,
            path=row.path,
            data_type=row.data_type,
        )


class CatalogCreatedResponse(BaseModel):
    """Result of ``create_catalog``."""

    catalog_id: UUID
    """ID of the new catalog."""


class SchemaCreatedResponse(BaseModel):
    """Result of ``create_schema``."""

    schema_id: UUID
    """ID of the new schema."""


class TableCreatedResponse(BaseModel):
    """Result of ``add_table``."""

    table_id: UUID
    """ID of the new table."""
