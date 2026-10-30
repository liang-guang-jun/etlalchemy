"""Measure definition and the default relationship routes it carries."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping

from etlalchemy.core.expression import FieldRef, RouteKey


@dataclasses.dataclass
class Measure:
    """A named aggregation over one field, with default relationship routes.

    ``routes`` is this measure's default relationship choice per
    ``(source alias, target alias)`` pair. A query's ``routes`` fill in pairs the
    measure does not bind, and pairs named by neither fall back to the highest
    priority, so an empty mapping means "use the highest priority everywhere".
    """

    name: str
    field: FieldRef
    routes: Mapping[RouteKey, int] = dataclasses.field(default_factory=dict)
