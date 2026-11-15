"""Value objects and internal entities shared by the semantic aggregates."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID

ALL_DIAGRAM = "All"
"""Name of the diagram every model owns; it shows every entity and cannot be removed."""


class Cardinality(StrEnum):
    """How many rows of one side a row of the other side relates to."""

    ONE_TO_MANY = "one_to_many"
    """One ``from`` row relates to many ``to`` rows."""

    ONE_TO_ONE = "one_to_one"
    """One ``from`` row relates to one ``to`` row."""

    MANY_TO_MANY = "many_to_many"
    """Rows on both sides relate to many rows on the other side."""


class FilterDirection(StrEnum):
    """Direction in which a relationship filter propagates."""

    SINGLE = "single"
    """The filter flows from the ``from`` side to the ``to`` side only."""

    BOTH = "both"
    """The filter flows in both directions."""


@dataclass(frozen=True, slots=True)
class FieldRef:
    """Reference to one field of one entity; a command argument, never an event."""

    entity: str
    """Name of the entity that owns the field."""
    field: str
    """Name of the field."""


@dataclass
class Entity:
    """A business entity backed by one catalog table."""

    entity_id: UUID
    """Identity of the entity, stable across renames and used as a comment target."""
    name: str
    """Name of the entity, used as its identity inside the model."""
    table_id: UUID
    """ID of the catalog table the entity maps to."""


@dataclass
class Relationship:
    """A field-level relation between two entities of the same model."""

    id: UUID
    """ID of the relationship."""
    from_refs: tuple[tuple[str, str], ...]
    """``(entity name, field name)`` pairs of the ``from`` side."""
    to_refs: tuple[tuple[str, str], ...]
    """``(entity name, field name)`` pairs of the ``to`` side, paired by position."""
    cardinality: Cardinality
    """Cardinality of the relation."""
    filter_direction: FilterDirection
    """Direction in which a filter flows across the relation."""
    priority: int = 0
    """Sort hint, lower first; duplicates are allowed."""


@dataclass
class Node:
    """One entity placed on a diagram canvas."""

    entity: str
    """Name of the placed entity."""
    x: float
    """Horizontal position on the canvas."""
    y: float
    """Vertical position on the canvas."""


@dataclass
class Diagram:
    """A canvas that shows a subset of the entities of one model."""

    name: str
    """Name of the diagram, unique inside the model."""
    order: int = 0
    """Sort hint, lower first."""
    nodes: dict[str, Node] = field(default_factory=dict)
    """Nodes of the diagram, keyed by entity name."""
