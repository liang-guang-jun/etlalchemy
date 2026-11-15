"""Ingestion bounded context: source connections and catalog imports."""

from etlalchemy.ingestion.aggregates import (
    DiscardedError,
    DuplicateConnectionError,
    ImportRun,
    IngestionError,
    InvalidImportRunStateError,
    MissingCredentialError,
    SourceConnection,
    UnknownCatalogError,
    UnknownConnectionError,
    UnknownImportRunError,
    UnknownSourceKindError,
    UnsupportedCredentialSchemeError,
    UnsupportedTypeError,
)
from etlalchemy.ingestion.application import IngestionApplication

__all__ = [
    "DiscardedError",
    "DuplicateConnectionError",
    "ImportRun",
    "IngestionApplication",
    "IngestionError",
    "InvalidImportRunStateError",
    "MissingCredentialError",
    "SourceConnection",
    "UnknownCatalogError",
    "UnknownConnectionError",
    "UnknownImportRunError",
    "UnknownSourceKindError",
    "UnsupportedCredentialSchemeError",
    "UnsupportedTypeError",
]
