"""Expression nodes for queries over a semantic model.

The nodes are pure value objects: they reference entities, fields and measures
by name and never hold registry instances. ``Pair`` is the key of one local
priority selection group and is shared with the routing helpers.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from uuid import UUID

#: Key of one local selection group: ``(source entity id, target entity id)``.
Pair = tuple[UUID, UUID]


@dataclass(frozen=True)
class FieldRef:
    """Reference to one field of one entity, by alias and field name."""

    entity: str
    name: str


@dataclass(frozen=True)
class MeasureRef:
    """Reference to a registered measure by name."""

    name: str


@dataclass(frozen=True)
class Filter:
    """A row filter applied to one field of one entity."""

    entity: str
    field: str
    operator: str
    value: object


@dataclass(frozen=True)
class OrderBy:
    """One ordering term over a dimension or measure reference."""

    ref: str
    descending: bool = False


@dataclass
class Query:
    """A query over dimensions, measures, filters and relationship routes.

    ``routes`` fixes, per ``(source entity id, target entity id)`` pair, which
    relationship priority the query traverses. It overrides the default routes
    carried by a measure, and pairs named by neither fall back to the highest
    priority. An empty mapping therefore means "use the highest priority
    everywhere".
    """

    dimensions: tuple[FieldRef, ...] = ()
    measures: tuple[MeasureRef, ...] = ()
    filters: tuple[Filter, ...] = ()
    routes: Mapping[Pair, int] = field(default_factory=dict)
    order_by: tuple[OrderBy, ...] = ()
    limit: int | None = None
