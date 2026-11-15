"""Errors shared by the catalog aggregates."""


class CatalogError(Exception):
    """Base class for errors raised by the catalog context."""


class DuplicateSchemaError(CatalogError):
    """Raised when a schema name is already registered in the catalog."""


class UnknownSchemaError(CatalogError):
    """Raised when a schema name is not registered in the catalog."""


class DuplicateTableError(CatalogError):
    """Raised when a table name is already registered in the schema."""


class UnknownTableError(CatalogError):
    """Raised when a table name is not registered in the schema."""


class DuplicateFieldError(CatalogError):
    """Raised when a field name is already used in a table."""


class UnknownFieldError(CatalogError):
    """Raised when a field name is not known in a table."""


class InvalidDataTypeError(CatalogError):
    """Raised when a data type is not part of the canonical vocabulary."""


class DiscardedError(RuntimeError):
    """Raised when a command targets an aggregate that was discarded."""
