"""Entry point that turns a semantic query into a compiled result."""

from __future__ import annotations

import logging
from collections.abc import Iterable

from etlalchemy.compile.builder import build_merge, build_select
from etlalchemy.compile.context import CompileContext
from etlalchemy.compile.formatting import format_sql
from etlalchemy.compile.plan import (
    FanoutRisk,
    JoinStep,
    detect_fanout,
    group_measures_by_entity,
    plan_ctes,
    plan_joins,
    plan_merge,
)
from etlalchemy.compile.report import (
    EXPRESSION_JOIN_UNBOUND,
    FANOUT_REJECTED,
    FANOUT_RISK,
    UNREACHABLE_DIMENSION,
    CompileEvent,
    JoinDecision,
)
from etlalchemy.compile.resolve import resolve_query
from etlalchemy.compile.result import CompiledQuery
from etlalchemy.compile.routes import select_edges
from etlalchemy.semantic.expression import Query
from etlalchemy.semantic.join import ExpressionJoin
from etlalchemy.semantic.model import SemanticModel
from etlalchemy.semantic.relationship import (
    Cardinality,
    FilterDirection,
    SemanticRelationship,
)

#: Logger used for diagnostics that do not fit in the returned values.
logger = logging.getLogger(__name__)

#: Values accepted by ``unreachable_dimensions``.
_UNREACHABLE_DIMENSIONS = frozenset({"error", "null"})

#: Number of fanout errors spelled out in one error message.
_MAX_REPORTED_FANOUT_ERRORS = 3


def _warn_expression_joins(
    edges: tuple[SemanticRelationship, ...],
    context: CompileContext,
) -> None:
    """Warn about expression joins that cannot parameterize their literals.

    An expression join is rendered as opaque SQL, so when literals are not
    inlined the caller is told that that join cannot bind them.
    """
    if context.inline_literals:
        return
    for relationship in edges:
        if isinstance(relationship.condition, ExpressionJoin):
            context.report.add(
                CompileEvent(
                    code=EXPRESSION_JOIN_UNBOUND,
                    severity="warning",
                    message=(
                        "expression join does not bind literals; ensure the "
                        f"expression is safe in relationship {relationship.name!r}"
                    ),
                    phase="routes",
                    relationship=relationship.name,
                )
            )


def _fanout_error_message(risks: tuple[FanoutRisk, ...]) -> str:
    """Return the error message describing the rejected fanout risks."""
    described = [
        f"Fanout detected for measure {risk.measure!r} on relationship "
        f"{risk.relationship!r}: {risk.reason}. Pre-aggregate the measure or "
        "change the aggregation."
        for risk in risks[:_MAX_REPORTED_FANOUT_ERRORS]
    ]
    if len(risks) > _MAX_REPORTED_FANOUT_ERRORS:
        described.append(f"and {len(risks) - _MAX_REPORTED_FANOUT_ERRORS} more")
    return " ".join(described)


def _report_fanout(risks: tuple[FanoutRisk, ...], context: CompileContext) -> None:
    """Record the warning-level fanout risks as events and log them."""
    for risk in risks:
        if risk.severity != "warning":
            continue
        context.report.add(
            CompileEvent(
                code=FANOUT_RISK,
                severity="warning",
                message=(
                    f"Fanout risk for measure {risk.measure!r} on relationship "
                    f"{risk.relationship!r}: {risk.reason}; the aggregation is "
                    "stable under duplicated rows"
                ),
                phase="fanout",
                measure=risk.measure,
                relationship=risk.relationship,
                payload=risk,
            )
        )
        logger.warning(
            "Fanout risk for measure %r on relationship %r: %s; the "
            "aggregation is stable under duplicated rows",
            risk.measure,
            risk.relationship,
            risk.reason,
        )


def _join_reason(relationship: SemanticRelationship) -> str:
    """Return the planner's reason for the join type of a relationship."""
    if relationship.filter_direction is FilterDirection.BOTH:
        return "both_filter"
    if relationship.cardinality is Cardinality.MANY_TO_MANY:
        return "many_to_many"
    if relationship.cardinality is Cardinality.ONE_TO_MANY:
        return "one_to_many_single"
    return "one_to_one"


def _join_decisions(steps: Iterable[JoinStep]) -> tuple[JoinDecision, ...]:
    """Turn planned join steps into the decisions carried by the report."""
    return tuple(
        JoinDecision(
            relationship=step.relationship.name,
            join_type=step.join_type,
            reason=_join_reason(step.relationship),
            reversed=step.reversed_edge,
        )
        for step in steps
    )


def compile_query(
    query: Query,
    model: SemanticModel,
    dialect: str = "databricks",
    *,
    inline_literals: bool = True,
    pretty: bool = True,
    unreachable_dimensions: str = "error",
    nulls_first: bool | None = None,
    identifier_case: str = "preserve",
    indent_width: int = 4,
) -> CompiledQuery:
    """Compile a semantic query into SQL, parameters and a report.

    The compilation resolves the query references, selects the relationships it
    traverses, plans one CTE per fact entity, and renders either a single
    select or the CTE merge query for ``dialect``. Fanout detection runs right
    after the edges are selected and before any plan is built, so a measure a
    join can duplicate rejects the query before any SQL is generated; risks
    that only warn are kept in the returned report.

    Args:
        query: Semantic query to compile.
        model: Model used to resolve entities and measures.
        dialect: Target SQL dialect understood by sqlglot; defaults to
            ``"databricks"``.
        inline_literals: When True (default), literal values are written into
            the SQL text and ``params`` is empty. When False, every literal
            becomes a placeholder and its value is collected in ``params``.
            Inlining is convenient for debugging and for values that come from
            trusted code, but it must not be used with untrusted input: it
            leaks values into SQL logs and defeats statement caching. Prefer
            ``inline_literals=False`` for anything user-supplied.
        pretty: When True, format the SQL with line breaks and indentation.
        unreachable_dimensions: ``"error"`` (default) rejects a measure entity
            that cannot aggregate by one of the query dimensions, naming the
            entity and the dimension. ``"null"`` projects NULL for that
            dimension inside its CTE, coalesces it in the merge query and
            records a warning in the compile report.
        nulls_first: Where NULL values sort in every ORDER BY term. ``True``
            renders ``NULLS FIRST``, ``False`` renders ``NULLS LAST``, and
            ``None`` (default) renders no NULLS clause at all, so the target
            database default applies. ``True`` and ``False`` make NULL
            placement identical across dialects, while ``None`` leaves it
            dialect dependent: ``ASC`` sorts NULLs last on Postgres but first on
            Databricks.
        identifier_case: ``"preserve"`` (default) keeps the casing of the
            compiled identifiers, ``"upper"`` uppercases every identifier and
            ``"lower"`` lowercases it.
        indent_width: Number of spaces per indentation level of the formatted
            SQL; defaults to 4.

    Returns:
        A :class:`~etlalchemy.compile.result.CompiledQuery` holding the SQL
        text, the parameters, the compile report, the dialect, the literal
        mode, the NULL placement and the formatting options used. With
        ``inline_literals`` False, ``params`` is a dict keyed by placeholder
        name (drivers that only accept positional arguments need the caller to
        convert the dict themselves); with ``inline_literals`` True it is an
        empty list.

    Raises:
        ValueError: If ``unreachable_dimensions`` is not ``"error"`` or
            ``"null"``, a query reference cannot be planned, or a measure can
            be duplicated by a fanout join (``sum``, ``count``, ``avg`` and
            every MANY_TO_MANY edge).
    """
    if unreachable_dimensions not in _UNREACHABLE_DIMENSIONS:
        raise ValueError(
            "unreachable_dimensions must be 'error' or 'null', "
            f"got {unreachable_dimensions!r}"
        )

    context = CompileContext(
        model=model,
        query=query,
        dialect=dialect,
        inline_literals=inline_literals,
        unreachable_dimensions=unreachable_dimensions,
        nulls_first=nulls_first,
    )
    resolved = resolve_query(query, context)
    edges = select_edges(resolved, context)
    _warn_expression_joins(edges, context)

    risks = detect_fanout(resolved, edges, model.registry)
    errors = tuple(risk for risk in risks if risk.severity == "error")
    if errors:
        for risk in errors:
            context.report.add(
                CompileEvent(
                    code=FANOUT_REJECTED,
                    severity="error",
                    message=(
                        f"Fanout detected for measure {risk.measure!r} on "
                        f"relationship {risk.relationship!r}: {risk.reason}."
                    ),
                    phase="fanout",
                    measure=risk.measure,
                    relationship=risk.relationship,
                    payload=risk,
                )
            )
        raise ValueError(_fanout_error_message(errors))
    _report_fanout(risks, context)

    grouped = group_measures_by_entity(resolved)
    if len(grouped) > 1:
        ctes = plan_ctes(
            resolved, grouped, edges, model.registry, unreachable_dimensions
        )
        context.report.cte_count = len(ctes)
        context.report.join_decisions = _join_decisions(
            step for cte in ctes for step in cte.steps
        )
        for cte in ctes:
            for dimension in cte.null_dimensions:
                context.report.add(
                    CompileEvent(
                        code=UNREACHABLE_DIMENSION,
                        severity="warning",
                        message=(
                            f"Dimension {dimension.output_alias!r} is NULL for "
                            f"entity {cte.entity_alias!r}"
                        ),
                        phase="plan",
                        entity=cte.entity_alias,
                        dimension=dimension.output_alias,
                    )
                )
        statement = build_merge(plan_merge(resolved, ctes), context)
    else:
        plan = plan_joins(resolved, edges, context)
        context.report.join_decisions = _join_decisions(plan.steps)
        statement = build_select(plan, context)

    raw_sql = statement.sql(dialect=dialect)
    final_sql = format_sql(
        raw_sql,
        dialect=dialect,
        identifier_case=identifier_case,
        indent_width=indent_width,
        pretty=pretty,
    )
    params: list[object] | dict[str, object] = (
        [] if inline_literals else dict(context.parameters)
    )
    return CompiledQuery(
        sql=final_sql,
        params=params,
        report=context.report,
        dialect=dialect,
        inline_literals=inline_literals,
        nulls_first=nulls_first,
        identifier_case=identifier_case,
        indent_width=indent_width,
    )
