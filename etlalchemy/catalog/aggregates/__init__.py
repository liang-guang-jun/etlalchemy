"""Aggregates of the catalog bounded context."""

from etlalchemy.catalog.aggregates.catalog import Catalog
from etlalchemy.catalog.aggregates.errors import (
    CatalogError,
    DiscardedError,
    DuplicateFieldError,
    DuplicateSchemaError,
    DuplicateTableError,
    InvalidDataTypeError,
    UnknownFieldError,
    UnknownSchemaError,
    UnknownTableError,
)
from etlalchemy.catalog.aggregates.schema import Schema
from etlalchemy.catalog.aggregates.table import Field, Table
from etlalchemy.catalog.aggregates.types import DataType

__all__ = [
    "Catalog",
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
