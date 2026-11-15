"""Read model interface for the ingestion context."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from eventsourcing.persistence import Tracking

from etlalchemy._vendor.eventsourcing.asyncio.persistence import AsyncTrackingRecorder


def as_uuid(value: UUID | str) -> UUID:
    """Returns the given value as a :class:`UUID`."""
    return value if isinstance(value, UUID) else UUID(value)


@dataclass(frozen=True)
class ConnectionRow:
    """A connection as stored in the ingestion read model."""

    connection_id: UUID
    """ID of the connection aggregate."""
    name: str
    """User-chosen name, unique across connections."""
    kind: str
    """Source kind, for example ``databricks``."""
    endpoint: str
    """Base URL or host of the source."""
    credential_ref: str | None
    """External secret reference, or ``None`` when an inline token is used."""
    has_inline_credential: bool
    """Whether the connection stores an inline token in its event state."""
    default_catalog: str | None
    """Catalog to use when an import does not name one."""
    options: dict[str, str]
    """Kind-specific options."""


@dataclass(frozen=True)
class ImportRunRow:
    """An import run as stored in the ingestion read model."""

    run_id: UUID
    """ID of the import run aggregate."""
    connection_id: UUID
    """Connection the import reads from."""
    target_catalog_id: UUID
    """Catalog the import writes into."""
    source_catalog: str | None
    """Source catalog that was imported."""
    include_schemas: list[str]
    """Schemas the import was restricted to."""
    include_tables: dict[str, list[str]]
    """Tables the import was restricted to, keyed by source schema."""
    schema_mapping: dict[str, str]
    """Target schema names keyed by source schema."""
    status: str
    """Run status: ``pending``, ``succeeded``, ``failed`` or ``abandoned``."""
    schema_count: int
    """Number of source schemas processed."""
    table_count: int
    """Number of source tables processed."""
    field_count: int
    """Number of source fields processed."""
    error: str | None
    """Error message when the run failed."""
    created_at: datetime
    """When the run was registered in the read model."""


class IngestionView(AsyncTrackingRecorder, ABC):
    """Materialised view of the ingestion aggregates.

    Every command method receives the :class:`Tracking` object of the event it
    applies and must write the view change and the tracking record in the same
    database transaction.
    """

    @abstractmethod
    async def create_table(self) -> None:
        """Creates the view tables and the tracking table if they do not exist."""
        ...

    @abstractmethod
    async def register_connection(
        self,
        connection_id: UUID,
        name: str,
        kind: str,
        endpoint: str,
        credential_ref: str | None,
        has_inline_credential: bool,
        default_catalog: str | None,
        options: dict[str, str],
        tracking: Tracking,
    ) -> None:
        """Registers a connection in the view."""
        ...

    @abstractmethod
    async def change_connection(
        self,
        connection_id: UUID,
        name: str | None,
        endpoint: str | None,
        default_catalog: str | None,
        options: dict[str, str] | None,
        tracking: Tracking,
    ) -> None:
        """Changes connection metadata, updating only non-``None`` fields."""
        ...

    @abstractmethod
    async def rotate_credential(
        self,
        connection_id: UUID,
        credential_ref: str | None,
        has_inline_credential: bool,
        tracking: Tracking,
    ) -> None:
        """Updates the credential pointer of a connection."""
        ...

    @abstractmethod
    async def discard_connection(self, connection_id: UUID, tracking: Tracking) -> None:
        """Marks a connection as discarded."""
        ...

    @abstractmethod
    async def get_connection(self, connection_id: UUID) -> ConnectionRow | None:
        """Returns the connection with the given id, or ``None``."""
        ...

    @abstractmethod
    async def find_connection_by_name(self, name: str) -> ConnectionRow | None:
        """Returns the live connection with the given name, or ``None``."""
        ...

    @abstractmethod
    async def list_connections(
        self,
        kind: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[ConnectionRow]:
        """Returns live connections, optionally filtered by kind and paged."""
        ...

    @abstractmethod
    async def register_import_run(
        self,
        run_id: UUID,
        connection_id: UUID,
        target_catalog_id: UUID,
        source_catalog: str | None,
        include_schemas: list[str],
        include_tables: dict[str, list[str]],
        schema_mapping: dict[str, str],
        tracking: Tracking,
    ) -> None:
        """Registers a run in the view with status ``pending``."""
        ...

    @abstractmethod
    async def finish_import_run(
        self,
        run_id: UUID,
        status: str,
        schema_count: int,
        table_count: int,
        field_count: int,
        error: str | None,
        tracking: Tracking,
    ) -> None:
        """Finalises a run in the view."""
        ...

    @abstractmethod
    async def get_import_run(self, run_id: UUID) -> ImportRunRow | None:
        """Returns the run with the given id, or ``None``."""
        ...

    @abstractmethod
    async def list_import_runs(
        self,
        connection_id: UUID | None = None,
        status: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[ImportRunRow]:
        """Returns runs, optionally filtered and paged, ordered by creation."""
        ...
