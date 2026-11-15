"""Table aggregate: owns the fields of one table."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import NAMESPACE_URL, UUID, uuid5

from eventsourcing.domain import Aggregate, AggregateCreated, event

from etlalchemy.catalog.aggregates.errors import (
    DiscardedError,
    DuplicateFieldError,
    UnknownFieldError,
)
from etlalchemy.catalog.aggregates.types import DataType

FIELD_NAMESPACE = uuid5(NAMESPACE_URL, "etlalchemy/catalog/field")
"""Namespace of the field identities, so they stay stable across replays."""


def field_identity(table_id: UUID, name: str) -> UUID:
    """Returns the identity of a field inside its table.

    Fields are registered by name, so events written before fields carried an
    identity replay without one; this derivation keeps their id stable instead
    of inventing a new random one on every replay.
    """
    return uuid5(FIELD_NAMESPACE, f"{table_id}:{name}")


@dataclass
class Field:
    """A field (column) of a table."""

    field_id: UUID
    """Identity of the field, stable across renames."""
    name: str
    """Name of the field, unique within its table."""
    data_type: DataType
    """Normalised data type of the field, for example ``DataType('integer')``."""
    nullable: bool = True
    """Whether the field may hold null values."""
    comment: str = ""
    """Free-form comment that documents the field."""


class Table(Aggregate):
    """Aggregate root for a table, owning its fields."""

    def __init__(self, schema_id: UUID, name: str, description: str = "") -> None:
        """Initialises a table that belongs to the given schema."""
        self.schema_id = schema_id
        self.name = name
        self.description = description
        self.fields: dict[str, Field] = {}
        self._is_discarded = False

    class Event(Aggregate.Event):
        """Base class for events raised by the table aggregate."""

    @dataclass(frozen=True)
    class Started(AggregateCreated):
        """Recorded when a table is created."""

        schema_id: UUID
        """ID of the schema that owns the table."""
        name: str
        """Name of the new table."""
        description: str = ""
        """Free-form description of the new table."""

    @dataclass(frozen=True)
    class FieldAdded(Event):
        """Recorded when a field is added to the table."""

        field_name: str
        """Name of the added field."""
        data_type: DataType
        """Normalised data type of the added field."""
        nullable: bool = True
        """Whether the added field may hold null values."""
        field_id: UUID | None = None
        """Identity of the field, or ``None`` for events written before it existed."""

    @dataclass(frozen=True)
    class FieldRemoved(Event):
        """Recorded when a field is removed from the table."""

        field_name: str
        """Name of the removed field."""

    @dataclass(frozen=True)
    class FieldTypeChanged(Event):
        """Recorded when only the data type of a field changes."""

        field_name: str
        """Name of the changed field."""
        data_type: DataType
        """Normalised data type of the field after the change."""

    @dataclass(frozen=True)
    class FieldNullabilityChanged(Event):
        """Recorded when only the nullability of a field changes."""

        field_name: str
        """Name of the changed field."""
        nullable: bool
        """Nullability of the field after the change."""

    @dataclass(frozen=True)
    class FieldCommentChanged(Event):
        """Recorded when the comment of a field changes."""

        field_name: str
        """Name of the changed field."""
        comment: str
        """Comment of the field after the change."""

    @event(FieldAdded)
    def add_field(
        self,
        field_name: str,
        data_type: DataType,
        nullable: bool = True,
        field_id: UUID | None = None,
    ) -> None:
        """Adds a field with the given name and type to the table."""
        self._ensure_not_discarded()
        if field_name in self.fields:
            msg = f"Field {field_name!r} already exists in table {self.name!r}"
            raise DuplicateFieldError(msg)
        self.fields[field_name] = Field(
            field_id=field_id or field_identity(self.id, field_name),
            name=field_name,
            data_type=data_type,
            nullable=nullable,
        )

    @event(FieldRemoved)
    def remove_field(self, field_name: str) -> None:
        """Removes the field with the given name from the table."""
        self._ensure_not_discarded()
        if field_name not in self.fields:
            msg = f"Field {field_name!r} does not exist in table {self.name!r}"
            raise UnknownFieldError(msg)
        del self.fields[field_name]

    def change_field(
        self,
        field_name: str,
        data_type: DataType | None = None,
        nullable: bool | None = None,
    ) -> None:
        """Changes the data type and/or nullability of an existing field.

        Each attribute is recorded by its own event, so a command that only
        changes nullability does not repeat the data type (and vice versa).
        """
        self._ensure_not_discarded()
        field = self._require_field(field_name)
        if data_type is None and nullable is None:
            msg = "change_field() requires a new data_type or nullable value"
            raise ValueError(msg)
        if data_type is not None and data_type != field.data_type:
            self._change_field_type(field_name, data_type)
        if nullable is not None and nullable != field.nullable:
            self._change_field_nullability(field_name, nullable)

    @event(FieldTypeChanged)
    def _change_field_type(self, field_name: str, data_type: DataType) -> None:
        """Records the new data type of a field."""
        self._require_field(field_name).data_type = data_type

    @event(FieldNullabilityChanged)
    def _change_field_nullability(self, field_name: str, nullable: bool) -> None:
        """Records the new nullability of a field."""
        self._require_field(field_name).nullable = nullable

    @event(FieldCommentChanged)
    def _change_field_comment(self, field_name: str, comment: str) -> None:
        """Records the new comment of a field."""
        self._require_field(field_name).comment = comment

    def change_field_comment(self, field_name: str, comment: str) -> None:
        """Documents a field with a free-form comment.

        A comment is metadata, not content: an empty value clears it, and an
        equal value is not recorded again so a retrying caller cannot grow the
        event stream.
        """
        self._ensure_not_discarded()
        field = self._require_field(field_name)
        if field.comment != comment:
            self._change_field_comment(field_name, comment)

    @dataclass(frozen=True)
    class Changed(Event):
        """Recorded when the table name or description changes."""

        name: str | None = None
        """New name, or ``None`` when unchanged."""
        description: str | None = None
        """New description, or ``None`` when unchanged."""

    @dataclass(frozen=True)
    class Discarded(Event):
        """Recorded when the table is discarded."""

    @dataclass(frozen=True)
    class FieldRenamed(Event):
        """Recorded when a field is renamed."""

        old_name: str
        """Name of the field before the rename."""
        new_name: str
        """Name of the field after the rename."""

    @event(Changed)
    def change(self, name: str | None = None, description: str | None = None) -> None:
        """Changes the table name and/or description."""
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
        """Marks the table as discarded."""
        self._ensure_not_discarded()
        self._is_discarded = True

    @event(FieldRenamed)
    def rename_field(self, old_name: str, new_name: str) -> None:
        """Renames a field, keeping the field registry consistent."""
        self._ensure_not_discarded()
        field = self._require_field(old_name)
        if old_name != new_name and new_name in self.fields:
            msg = f"Field {new_name!r} already exists in table {self.name!r}"
            raise DuplicateFieldError(msg)
        if old_name != new_name:
            del self.fields[old_name]
            field.name = new_name
            self.fields[new_name] = field

    def _ensure_not_discarded(self) -> None:
        """Raises DiscardedError when the table has been discarded."""
        if self._is_discarded:
            msg = "table is discarded"
            raise DiscardedError(msg)

    def _require_field(self, field_name: str) -> Field:
        """Returns the field with the given name, or raises UnknownFieldError."""
        try:
            return self.fields[field_name]
        except KeyError:
            msg = f"Field {field_name!r} does not exist in table {self.name!r}"
            raise UnknownFieldError(msg) from None
