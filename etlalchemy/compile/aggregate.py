"""Build the SQL aggregate expression of a resolved measure.

``sum``, ``count``, ``avg``, ``min`` and ``max`` wrap the measure's single field
in their sqlglot node. ``count_distinct`` wraps one or more columns in
``exp.Distinct``: ``exp.Count(this=exp.Distinct(expressions=[...]))`` renders
``COUNT(DISTINCT col)`` for one column and ``COUNT(DISTINCT col1, col2)`` for
several columns on dialects such as Databricks and Spark; sqlglot emulates the
multi-column form with a row constructor where the dialect needs one, for
example ``COUNT(DISTINCT (col1, col2))`` on Postgres.
"""

from __future__ import annotations

from typing import cast

from sqlglot import exp

from etlalchemy.compile.context import CompileContext
from etlalchemy.compile.resolve import ResolvedMeasure

#: Aggregations that wrap their single field in a sqlglot aggregate node.
_SIMPLE_AGGREGATIONS: dict[str, type[exp.AggFunc]] = {
    "avg": exp.Avg,
    "count": exp.Count,
    "max": exp.Max,
    "min": exp.Min,
    "sum": exp.Sum,
}


def build_aggregation(
    measure: ResolvedMeasure,
    context: CompileContext,
) -> exp.Expression:
    """Return the aggregate expression of one resolved measure.

    Args:
        measure: Resolved measure with its entity, single field and fields.
        context: Compilation state used to render the table alias.

    Returns:
        The sqlglot aggregate, for example ``SUM(o.amount)``,
        ``COUNT(DISTINCT o.user_id, o.order_id)`` or ``COUNT(*)``.

    ``count`` renders ``COUNT(*)`` when the measure has no field and no fields,
    which reads no column at all, and ``COUNT(field)`` otherwise. ``exp.Star()``
    takes no arguments in the sqlglot version in use and renders ``*``.

    Raises:
        ValueError: If ``count_distinct`` has neither a field nor fields, or if
            another aggregation has no field. ``COUNT(*)`` relies on the
            resolve layer having set ``measure.entity``; that is guaranteed
            before this builder runs.
    """
    alias = context.sql_alias(measure.entity)
    aggregation = measure.measure.aggregation
    if aggregation == "count" and measure.field is None and not measure.fields:
        return exp.Count(this=exp.Star())
    if aggregation == "count_distinct":
        columns = [exp.column(field.name, table=alias) for field in measure.fields]
        if not columns:
            if measure.field is None:
                raise ValueError("count_distinct requires field or fields")
            columns = [exp.column(measure.field.name, table=alias)]
        return exp.Count(this=exp.Distinct(expressions=columns))

    if measure.field is None:
        raise ValueError(f"aggregation {aggregation!r} requires a field")
    aggregate = _SIMPLE_AGGREGATIONS[aggregation]
    return cast(
        exp.Expression, aggregate(this=exp.column(measure.field.name, table=alias))
    )


__all__ = ["build_aggregation"]
