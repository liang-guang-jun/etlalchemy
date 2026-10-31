"""Measure definition and the default relationship routes it carries."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping

from etlalchemy.semantic.expression import FieldRef, RouteKey

#: Aggregations the first-version compiler understands.
SUPPORTED_AGGREGATIONS = ("avg", "count", "count_distinct", "max", "min", "sum")


@dataclasses.dataclass
class Measure:
    """A named aggregation over one field or a tuple of fields.

    ``field`` is the single column the aggregation is computed over. It is
    required for ``sum``, ``avg``, ``min`` and ``max``, optional for ``count``
    and one of the two alternatives for ``count_distinct``.

    ``count`` has two forms: with ``field`` it renders ``COUNT(field)`` and
    skips NULL values, while without ``field`` and ``fields`` it renders
    ``COUNT(*)`` and reads no column at all, which lets the compiler prune
    every column the query does not otherwise need.

    ``fields`` is the tuple of columns of a multi-column ``count_distinct``.
    ``field`` and ``fields`` are mutually exclusive: ``count_distinct`` takes
    exactly one of them, ``count`` takes only ``field``, and the remaining
    aggregations take only ``field``.

    ``entity`` names the fact entity of a ``COUNT(*)`` measure. It is only read
    when ``field`` and ``fields`` are both empty, because a measure without a
    field reference has no other way to say which entity it counts;
    ``resolve_query`` raises ``ValueError`` when it is missing. For every other
    measure the field already implies the entity and ``entity`` is ignored.

    ``routes`` is this measure's default relationship choice per
    ``(source alias, target alias)`` pair. A query's ``routes`` fill in pairs the
    measure does not bind, and pairs named by neither fall back to the highest
    priority, so an empty mapping means "use the highest priority everywhere".

    ``aggregation`` is one of :data:`SUPPORTED_AGGREGATIONS` and defaults to
    ``"sum"``. It decides which SQL aggregate the compiler emits and how a
    fanout risk is handled: ``sum``, ``count`` and ``avg`` raise ``ValueError``
    when a join can duplicate the measure rows, while ``min``, ``max`` and
    ``count_distinct`` only record a warning because their value is stable
    under duplication.

    A multi-column ``count_distinct`` renders ``COUNT(DISTINCT col1, col2)``,
    which Databricks and Spark SQL support natively. sqlglot emulates it with a
    row constructor on dialects such as Postgres, so the exact text depends on
    the target dialect. Every field of ``fields`` must belong to the same
    entity as the measure.
    """

    name: str
    field: FieldRef | None = None
    routes: Mapping[RouteKey, int] = dataclasses.field(default_factory=dict)
    aggregation: str = "sum"
    fields: tuple[FieldRef, ...] = ()
    entity: str | None = None

    def __post_init__(self) -> None:
        """Normalize the aggregation and validate the column arguments.

        ``count`` accepts an empty ``field`` for ``COUNT(*)`` and an optional
        ``field`` for ``COUNT(field)``, but never ``fields``. ``count_distinct``
        keeps requiring exactly one of ``field`` and ``fields``. ``sum``,
        ``avg``, ``min`` and ``max`` still require ``field`` and reject
        ``fields``.

        Raises:
            ValueError: If the aggregation is unknown, ``count_distinct`` gets
                both or neither of ``field`` and ``fields``, ``count`` gets a
                non-empty ``fields``, or another aggregation gets no ``field``
                or a non-empty ``fields``.
        """
        self.aggregation = self.aggregation.lower()
        if self.aggregation not in SUPPORTED_AGGREGATIONS:
            raise ValueError(
                f"Unsupported aggregation {self.aggregation!r}; "
                f"expected one of {SUPPORTED_AGGREGATIONS}"
            )
        if self.aggregation == "count_distinct":
            if self.field is not None and self.fields:
                raise ValueError(
                    "count_distinct accepts either field or fields, not both"
                )
            if self.field is None and not self.fields:
                raise ValueError("count_distinct requires a field or fields")
            return
        if self.aggregation == "count":
            if self.fields:
                raise ValueError(
                    "count does not accept fields; pass field for COUNT(field) "
                    "or leave both empty for COUNT(*)"
                )
            return
        if self.field is None:
            raise ValueError(f"aggregation {self.aggregation!r} requires a field")
        if self.fields:
            raise ValueError(
                f"aggregation {self.aggregation!r} does not accept fields; "
                "use count_distinct for multiple columns"
            )
