"""Merge the relationship routes of a measure with those of a query."""

from __future__ import annotations

from collections.abc import Mapping

from etlalchemy.semantic.expression import Query, RouteKey
from etlalchemy.semantic.measure import Measure


def effective_routes(measure: Measure, query: Query) -> Mapping[RouteKey, int]:
    """Merge measure routes over query routes.

    The measure's routes are authoritative: a pair bound by the measure always
    keeps the measure's priority. The query's routes only fill in pairs the
    measure does not bind. Neither argument is modified, and pairs named by
    neither mapping are absent from the result, which tells the compilation
    layer to fall back to the highest priority.
    """
    merged: dict[RouteKey, int] = dict(query.routes)
    merged.update(measure.routes)
    return merged
