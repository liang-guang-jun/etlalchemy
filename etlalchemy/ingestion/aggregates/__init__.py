"""Aggregates of the ingestion bounded context."""

from etlalchemy.ingestion.aggregates.connection import SourceConnection
from etlalchemy.ingestion.aggregates.errors import (
    DiscardedError,
    DuplicateConnectionError,
    IngestionError,
    InvalidImportRunStateError,
    MissingCredentialError,
    UnknownCatalogError,
    UnknownConnectionError,
    UnknownImportRunError,
    UnknownSourceKindError,
    UnsupportedCredentialSchemeError,
    UnsupportedTypeError,
)
from etlalchemy.ingestion.aggregates.import_run import ImportRun

__all__ = [
    "DiscardedError",
    "DuplicateConnectionError",
    "ImportRun",
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
