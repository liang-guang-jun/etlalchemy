"""ImportRun aggregate: one import attempt from a connection into a catalog."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from eventsourcing.domain import Aggregate, AggregateCreated, event

from etlalchemy.ingestion.aggregates.errors import InvalidImportRunStateError


class ImportRun(Aggregate):
    """Tracks one import attempt.

    The run is created before the import starts and is finalised with a single
    ``Succeeded``, ``Failed`` or ``Abandoned`` event. Intermediate counters are
    accumulated in memory and only persisted with the terminal event, so a
    crashed process leaves the run in the ``pending`` state until it is
    abandoned manually.
    """

    def __init__(
        self,
        connection_id: UUID,
        target_catalog_id: UUID,
        source_catalog: str | None = None,
        include_schemas: list[str] | None = None,
        include_tables: dict[str, list[str]] | None = None,
        schema_mapping: dict[str, str] | None = None,
    ) -> None:
        """Initialises a run in the ``pending`` state."""
        self.connection_id = connection_id
        self.target_catalog_id = target_catalog_id
        self.source_catalog = source_catalog
        self.include_schemas = list(include_schemas or [])
        self.include_tables = {
            schema: list(tables) for schema, tables in (include_tables or {}).items()
        }
        self.schema_mapping = dict(schema_mapping or {})
        self.status = "pending"
        self.schema_count = 0
        self.table_count = 0
        self.field_count = 0
        self.error: str | None = None

    class Event(Aggregate.Event):
        """Base class for events raised by the ImportRun aggregate."""

    @dataclass(frozen=True)
    class Started(AggregateCreated):
        """Recorded when a run is created."""

        connection_id: UUID
        """Connection the import reads from."""
        target_catalog_id: UUID
        """Catalog the import writes into."""
        source_catalog: str | None = None
        """Source catalog to import, or ``None`` for the connection default."""
        include_schemas: list[str] = field(default_factory=list)
        """Only import these schemas when non-empty."""
        include_tables: dict[str, list[str]] = field(default_factory=dict)
        """Only import these tables, keyed by source schema name."""
        schema_mapping: dict[str, str] = field(default_factory=dict)
        """Rename source schemas in the target catalog."""

    @dataclass(frozen=True)
    class Succeeded(Event):
        """Recorded when an import finishes without error."""

        schema_count: int
        """Number of source schemas processed."""
        table_count: int
        """Number of source tables processed."""
        field_count: int
        """Number of source fields processed."""

    @dataclass(frozen=True)
    class Failed(Event):
        """Recorded when an import stops with an error."""

        error: str
        """Message describing why the import stopped."""
        schema_count: int
        """Number of source schemas processed before the failure."""
        table_count: int
        """Number of source tables processed before the failure."""
        field_count: int
        """Number of source fields processed before the failure."""

    @dataclass(frozen=True)
    class Abandoned(Event):
        """Recorded when a stale pending run is abandoned manually."""

        reason: str
        """Reason the run was abandoned."""

    def record_schema(self) -> None:
        """Increments the schema counter (persisted only by a terminal event)."""
        self.schema_count += 1

    def record_table(self) -> None:
        """Increments the table counter (persisted only by a terminal event)."""
        self.table_count += 1

    def record_field(self) -> None:
        """Increments the field counter (persisted only by a terminal event)."""
        self.field_count += 1

    @event(Succeeded)
    def succeed(self, schema_count: int, table_count: int, field_count: int) -> None:
        """Marks the run as succeeded with the final counters."""
        self._ensure_pending()
        self.status = "succeeded"
        self.schema_count = schema_count
        self.table_count = table_count
        self.field_count = field_count

    @event(Failed)
    def fail(
        self,
        error: str,
        schema_count: int,
        table_count: int,
        field_count: int,
    ) -> None:
        """Marks the run as failed with the final counters and the error."""
        self._ensure_pending()
        self.status = "failed"
        self.error = error
        self.schema_count = schema_count
        self.table_count = table_count
        self.field_count = field_count

    @event(Abandoned)
    def abandon(self, reason: str) -> None:
        """Marks a stale pending run as abandoned."""
        self._ensure_pending()
        self.status = "abandoned"
        self.error = reason

    def _ensure_pending(self) -> None:
        """Raises when the run is not in the ``pending`` state."""
        if self.status != "pending":
            msg = f"import run is already {self.status}"
            raise InvalidImportRunStateError(msg)
