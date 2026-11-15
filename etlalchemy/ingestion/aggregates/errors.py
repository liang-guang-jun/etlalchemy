"""Errors shared by the ingestion aggregates."""


class IngestionError(Exception):
    """Base class for errors raised by the ingestion context."""


class DuplicateConnectionError(IngestionError):
    """Raised when a connection name is already registered."""


class UnknownConnectionError(IngestionError):
    """Raised when a connection id or name is not known."""


class UnknownImportRunError(IngestionError):
    """Raised when an import run id is not known."""


class UnknownSourceKindError(IngestionError):
    """Raised when no factory is registered for a source kind."""


class UnknownCatalogError(IngestionError):
    """Raised when a data source has no catalog with the given name."""


class MissingCredentialError(IngestionError):
    """Raised when a connection carries neither a reference nor an inline token."""


class UnsupportedCredentialSchemeError(IngestionError):
    """Raised when a credential reference uses a scheme no provider handles."""


class UnsupportedTypeError(IngestionError):
    """Raised when a column type cannot be mapped to the catalog vocabulary."""


class InvalidImportRunStateError(IngestionError):
    """Raised when an ImportRun transition is not allowed from its current state."""


class DiscardedError(IngestionError, RuntimeError):
    """Raised when a command targets an aggregate that was discarded."""
