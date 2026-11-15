"""Catalog aggregate: registers the schemas of a data catalog."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from eventsourcing.domain import Aggregate, AggregateCreated, event

from etlalchemy.catalog.aggregates.errors import (
    DiscardedError,
    DuplicateSchemaError,
    UnknownSchemaError,
)


class Catalog(Aggregate):
    """Aggregate root that registers the schemas of a data catalog.

    Schemas are separate aggregates, so this aggregate only keeps the mapping
    from schema name to schema id. Registering and unregistering a schema are
    its two state transitions.
    """

    def __init__(self, name: str, description: str = "") -> None:
        """Initialises a catalog with the given name and description."""
        self.name = name
        self.description = description
        self.schemas: dict[str, UUID] = {}
        self._is_discarded = False

    class Event(Aggregate.Event):
        """Base class for events raised by the catalog aggregate."""

    @dataclass(frozen=True)
    class Started(AggregateCreated):
        """Recorded when a catalog is created."""

        name: str
        """Name of the new catalog."""
        description: str = ""
        """Free-form description of the new catalog."""

    @dataclass(frozen=True)
    class SchemaRegistered(Event):
        """Recorded when a schema is registered under a name."""

        schema_name: str
        """Name the schema is registered under."""
        schema_id: UUID
        """ID of the schema aggregate."""
        description: str = ""
        """Free-form description of the schema."""

    @dataclass(frozen=True)
    class SchemaUnregistered(Event):
        """Recorded when a schema name is unregistered."""

        schema_name: str
        """Name the schema was registered under."""

    @dataclass(frozen=True)
    class Changed(Event):
        """Recorded when the catalog name or description changes."""

        name: str | None = None
        """New name, or ``None`` when unchanged."""
        description: str | None = None
        """New description, or ``None`` when unchanged."""

    @dataclass(frozen=True)
    class Discarded(Event):
        """Recorded when the catalog is discarded."""

    @dataclass(frozen=True)
    class SchemaNameChanged(Event):
        """Recorded when a registered schema is renamed."""

        schema_id: UUID
        """ID of the renamed schema aggregate."""
        new_name: str
        """New name the schema is registered under."""

    @event(SchemaRegistered)
    def register_schema(self, schema_name: str, schema_id: UUID, description: str = "") -> None:
        """Registers a schema aggregate under the given name."""
        self._ensure_not_discarded()
        if schema_name in self.schemas:
            msg = f"Schema {schema_name!r} already exists in catalog {self.name!r}"
            raise DuplicateSchemaError(msg)
        self.schemas[schema_name] = schema_id

    @event(SchemaUnregistered)
    def unregister_schema(self, schema_name: str) -> None:
        """Unregisters the schema with the given name."""
        self._ensure_not_discarded()
        self.schema_id(schema_name)
        del self.schemas[schema_name]

    @event(Changed)
    def change(self, name: str | None = None, description: str | None = None) -> None:
        """Changes the catalog name and/or description."""
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
        """Marks the catalog as discarded."""
        self._ensure_not_discarded()
        self._is_discarded = True

    @event(SchemaNameChanged)
    def rename_schema(self, schema_id: UUID, new_name: str) -> None:
        """Renames a registered schema, keeping the name to id registry consistent."""
        self._ensure_not_discarded()
        old_name = self._registered_name(schema_id)
        existing_id = self.schemas.get(new_name)
        if existing_id is not None and existing_id != schema_id:
            msg = f"Schema {new_name!r} already exists in catalog {self.name!r}"
            raise DuplicateSchemaError(msg)
        if old_name != new_name:
            del self.schemas[old_name]
        self.schemas[new_name] = schema_id

    def _registered_name(self, schema_id: UUID) -> str:
        """Returns the name a schema is registered under."""
        for name, registered_id in self.schemas.items():
            if registered_id == schema_id:
                return name
        msg = f"Schema {schema_id} is not registered in catalog {self.name!r}"
        raise UnknownSchemaError(msg)

    def _ensure_not_discarded(self) -> None:
        """Raises DiscardedError when the catalog has been discarded."""
        if self._is_discarded:
            msg = "catalog is discarded"
            raise DiscardedError(msg)

    def schema_id(self, schema_name: str) -> UUID:
        """Returns the id of the schema registered under the given name."""
        try:
            return self.schemas[schema_name]
        except KeyError:
            msg = f"Schema {schema_name!r} does not exist in catalog {self.name!r}"
            raise UnknownSchemaError(msg) from None
