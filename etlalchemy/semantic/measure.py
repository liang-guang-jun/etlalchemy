"""Measure definition and the default relationship routes it carries."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping

from etlalchemy.semantic.expression import FieldRef, RouteKey

#: Aggregations the first-version compiler understands.
SUPPORTED_AGGREGATIONS = ("avg", "count", "max", "min", "sum")


@dataclasses.dataclass
class Measure:
    """A named aggregation over one field, with default relationship routes.

    ``routes`` is this measure's default relationship choice per
    ``(source alias, target alias)`` pair. A query's ``routes`` fill in pairs the
    measure does not bind, and pairs named by neither fall back to the highest
    priority, so an empty mapping means "use the highest priority everywhere".

    ``aggregation`` is one of :data:`SUPPORTED_AGGREGATIONS`; it decides which
    SQL aggregate the compiler emits.
    """

    name: str
    field: FieldRef
    routes: Mapping[RouteKey, int] = dataclasses.field(default_factory=dict)
    aggregation: str = "sum"

    def __post_init__(self) -> None:
        """Normalize and validate the aggregation name."""
        self.aggregation = self.aggregation.lower()
        if self.aggregation not in SUPPORTED_AGGREGATIONS:
            raise ValueError(
                f"Unsupported aggregation {self.aggregation!r}; "
                f"expected one of {SUPPORTED_AGGREGATIONS}"
            )
