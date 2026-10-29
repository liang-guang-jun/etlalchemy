"""Merge the relationship routes of a measure with those of a query."""

from __future__ import annotations

from collections.abc import Mapping

from etlalchemy.core.expression import Pair, Query
from etlalchemy.core.measure import Measure


def effective_routes(measure: Measure, query: Query) -> Mapping[Pair, int]:
    """Merge measure routes over query routes.

    The measure's routes are authoritative: a pair bound by the measure always
    keeps the measure's priority. The query's routes only fill in pairs the
    measure does not bind.
    """
    merged: dict[Pair, int] = dict(query.routes)
    merged.update(measure.routes)
    return merged
