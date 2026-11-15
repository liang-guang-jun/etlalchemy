"""Catalog bounded context: schemas, tables and fields of a data catalog."""

from etlalchemy.catalog.aggregates import (
    Catalog,
    CatalogError,
    DataType,
    DiscardedError,
    DuplicateFieldError,
    DuplicateSchemaError,
    DuplicateTableError,
    Field,
    InvalidDataTypeError,
    Schema,
    Table,
    UnknownFieldError,
    UnknownSchemaError,
    UnknownTableError,
)
from etlalchemy.catalog.application import CatalogApplication

__all__ = [
    "Catalog",
    "CatalogApplication",
    "CatalogError",
    "DataType",
    "DiscardedError",
    "DuplicateFieldError",
    "DuplicateSchemaError",
    "DuplicateTableError",
    "Field",
    "InvalidDataTypeError",
    "Schema",
    "Table",
    "UnknownFieldError",
    "UnknownSchemaError",
    "UnknownTableError",
]
