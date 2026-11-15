"""Schema aggregate: registers the tables of one schema."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from eventsourcing.domain import Aggregate, AggregateCreated, event

from etlalchemy.catalog.aggregates.errors import (
    DiscardedError,
    DuplicateTableError,
    UnknownTableError,
)


class Schema(Aggregate):
    """Aggregate root for a schema, registering its tables by id.

    Tables are separate aggregates, so this aggregate only keeps the mapping
    from table name to table id.
    """

    def __init__(self, catalog_id: UUID, name: str, description: str = "") -> None:
        """Initialises a schema that belongs to the given catalog."""
        self.catalog_id = catalog_id
        self.name = name
        self.description = description
        self.tables: dict[str, UUID] = {}
        self._is_discarded = False

    class Event(Aggregate.Event):
        """Base class for events raised by the schema aggregate."""

    @dataclass(frozen=True)
    class Started(AggregateCreated):
        """Recorded when a schema is created."""

        catalog_id: UUID
        """ID of the catalog that owns the schema."""
        name: str
        """Name of the new schema."""
        description: str = ""
        """Free-form description of the new schema."""

    @dataclass(frozen=True)
    class TableRegistered(Event):
        """Recorded when a table is registered under a name."""

        table_name: str
        """Name the table is registered under."""
        table_id: UUID
        """ID of the table aggregate."""

    @dataclass(frozen=True)
    class TableUnregistered(Event):
        """Recorded when a table name is unregistered."""

        table_name: str
        """Name the table was registered under."""

    @dataclass(frozen=True)
    class Changed(Event):
        """Recorded when the schema name or description changes."""

        name: str | None = None
        """New name, or ``None`` when unchanged."""
        description: str | None = None
        """New description, or ``None`` when unchanged."""

    @dataclass(frozen=True)
    class Discarded(Event):
        """Recorded when the schema is discarded."""

    @dataclass(frozen=True)
    class TableNameChanged(Event):
        """Recorded when a registered table is renamed."""

        table_id: UUID
        """ID of the renamed table aggregate."""
        new_name: str
        """New name the table is registered under."""

    @event(TableRegistered)
    def register_table(self, table_name: str, table_id: UUID) -> None:
        """Registers a table aggregate under the given name."""
        self._ensure_not_discarded()
        if table_name in self.tables:
            msg = f"Table {table_name!r} already exists in schema {self.name!r}"
            raise DuplicateTableError(msg)
        self.tables[table_name] = table_id

    @event(TableUnregistered)
    def unregister_table(self, table_name: str) -> None:
        """Unregisters the table with the given name."""
        self._ensure_not_discarded()
        self.table_id(table_name)
        del self.tables[table_name]

    @event(Changed)
    def change(self, name: str | None = None, description: str | None = None) -> None:
        """Changes the schema name and/or description."""
        self._ensure_not_discarded()
        if name is None and description is None:
            msg = "change() requires a new name or description"
            raise ValueError(msg)
        if name is not None:
            self.name = name
        if description is not None:
            self.description = description

    @event(Discarded)
    def discard(self) -> None:
        """Marks the schema as discarded."""
        self._ensure_not_discarded()
        self._is_discarded = True

    @event(TableNameChanged)
    def rename_table(self, table_id: UUID, new_name: str) -> None:
        """Renames a registered table, keeping the name to id registry consistent."""
        self._ensure_not_discarded()
        old_name = self._registered_name(table_id)
        existing_id = self.tables.get(new_name)
        if existing_id is not None and existing_id != table_id:
            msg = f"Table {new_name!r} already exists in schema {self.name!r}"
            raise DuplicateTableError(msg)
        if old_name != new_name:
            del self.tables[old_name]
        self.tables[new_name] = table_id

    def _registered_name(self, table_id: UUID) -> str:
        """Returns the name a table is registered under."""
        for name, registered_id in self.tables.items():
            if registered_id == table_id:
                return name
        msg = f"Table {table_id} is not registered in schema {self.name!r}"
        raise UnknownTableError(msg)

    def _ensure_not_discarded(self) -> None:
        """Raises DiscardedError when the schema has been discarded."""
        if self._is_discarded:
            msg = "schema is discarded"
            raise DiscardedError(msg)

    def table_id(self, table_name: str) -> UUID:
        """Returns the id of the table registered under the given name."""
        try:
            return self.tables[table_name]
        except KeyError:
            msg = f"Table {table_name!r} does not exist in schema {self.name!r}"
            raise UnknownTableError(msg) from None
