"""Build sqlglot statements from join and merge plans.

``ON`` clauses are not assembled here: every join step asks its relationship's
``JoinCondition`` for the rendered predicate and parameters, so an equi join and
an expression join reach the statement through the same code path.

Results are rendered per dialect by the caller. ORDER BY terms are rendered
here from the column, the direction and ``CompileContext.nulls_first`` rather
than through ``exp.Ordered``: sqlglot drops ``NULLS FIRST``/``NULLS LAST`` when
it matches the dialect default and adds one when the flag is unset, which hides
whether the caller asked for an explicit NULL placement.
"""

from __future__ import annotations

from typing import Any, cast

from sqlglot import condition as sql_condition
from sqlglot import exp

from etlalchemy.compile.context import CompileContext
from etlalchemy.compile.plan import CTEPlan, JoinPlan, JoinStep, MergePlan
from etlalchemy.compile.predicate import build_condition
from etlalchemy.compile.resolve import ResolvedDimension
from etlalchemy.semantic.expression import OrderBy
from etlalchemy.semantic.rowset import SemanticEntity

_AGGREGATIONS: dict[str, Any] = {
    "avg": exp.Avg,
    "count": exp.Count,
    "max": exp.Max,
    "min": exp.Min,
    "sum": exp.Sum,
}

#: NULLS suffix appended to an ORDER BY term for each ``nulls_first`` value.
_NULLS_SUFFIX: dict[bool | None, str] = {
    None: "",
    True: " NULLS FIRST",
    False: " NULLS LAST",
}


def _table(entity: SemanticEntity, alias: str) -> exp.Table:
    """Return the aliased table expression of an entity's rowset."""
    return cast(exp.Table, exp.to_table(entity.relation.name).as_(alias))


def _join_condition(step: JoinStep, context: CompileContext) -> exp.Expression:
    """Return the ON clause of one join step from its join condition."""
    relationship = step.relationship
    source_entity = context.entity_by_alias[relationship.source_alias()]
    target_entity = context.entity_by_alias[relationship.target_alias()]
    sql, _ = relationship.condition.to_sql(
        context.sql_alias(source_entity),
        context.sql_alias(target_entity),
        context.bind_literals,
        context.add_parameter,
    )
    return cast(exp.Expression, sql_condition(sql))


def _join(step: JoinStep, context: CompileContext) -> exp.Join:
    """Build one join clause for a join step."""
    new_entity = context.entity_by_alias[step.new_alias]
    return exp.Join(
        this=_table(new_entity, context.sql_alias(new_entity)),
        kind=step.join_type,
        on=_join_condition(step, context),
    )


def _aggregate(name: str, column: exp.Column) -> exp.Expression:
    """Build the aggregate expression for one measure aggregation."""
    if name == "count_distinct":
        return exp.Count(this=exp.Distinct(expressions=[column]))
    return cast(exp.Expression, _AGGREGATIONS[name](this=column))


def _where(conditions: list[exp.Expression]) -> exp.Expression | None:
    """Combine several conditions with AND."""
    if not conditions:
        return None
    combined: Any = conditions[0]
    for condition in conditions[1:]:
        combined = exp.and_(combined, condition)
    return cast(exp.Expression, combined)


def _ordered_term(term: OrderBy, context: CompileContext) -> exp.Expression:
    """Render one ORDER BY term with the configured NULL placement.

    The term is built as text because sqlglot's ``exp.Ordered`` omits
    ``NULLS FIRST``/``NULLS LAST`` whenever the request matches the dialect
    default and appends one when the flag is unset. Rendering the column, the
    direction and the NULLS suffix here keeps ``nulls_first`` exact on every
    dialect; with ``None`` no NULLS clause is emitted at all.
    """
    column = exp.column(term.ref).sql(dialect=context.dialect)
    direction = " DESC" if term.descending else ""
    return exp.Var(this=f"{column}{direction}{_NULLS_SUFFIX[context.nulls_first]}")


def _apply_order_and_limit(
    query: exp.Select,
    order_terms: tuple[OrderBy, ...],
    row_limit: int | None,
    context: CompileContext,
) -> exp.Select:
    """Append ORDER BY and LIMIT clauses to a select."""
    for term in order_terms:
        query = query.order_by(_ordered_term(term, context))
    if row_limit is not None:
        query = query.limit(row_limit)
    return query


def build_select(plan: JoinPlan, context: CompileContext) -> exp.Select:
    """Build a sqlglot SELECT AST for a single-fact join plan.

    Args:
        plan: Planned base entity, joins, grain and projections.
        context: Compilation state used for SQL aliases and parameters.

    Returns:
        A sqlglot SELECT expression, still independent of any dialect.
    """
    query = exp.Select()
    for dimension in plan.group_by:
        query = query.select(
            exp.alias_(
                exp.column(
                    dimension.field.name,
                    table=context.sql_alias(dimension.entity),
                ),
                dimension.output_alias,
            )
        )
    for measure in plan.aggregations:
        query = query.select(
            exp.alias_(
                _aggregate(
                    measure.measure.aggregation,
                    exp.column(
                        measure.field.name,
                        table=context.sql_alias(measure.entity),
                    ),
                ),
                measure.output_alias,
            )
        )

    query = query.from_(_table(plan.base_entity, context.sql_alias(plan.base_entity)))
    for step in plan.steps:
        query = query.join(_join(step, context))

    where = _where([build_condition(predicate, context) for predicate in plan.filters])
    if where is not None:
        query = query.where(where)

    if plan.group_by:
        query = query.group_by(
            *[
                exp.column(
                    dimension.field.name,
                    table=context.sql_alias(dimension.entity),
                )
                for dimension in plan.group_by
            ]
        )
    return _apply_order_and_limit(query, plan.order_terms, plan.row_limit, context)


def build_cte(cte: CTEPlan, context: CompileContext) -> exp.CTE:
    """Build one pre-aggregation CTE.

    Args:
        cte: CTE plan with its fact entity, grain, joins and filters.
        context: Compilation state used for SQL aliases and parameters.

    Returns:
        The CTE node wrapping the aggregate select.
    """
    base_entity = context.entity_by_alias[cte.entity_alias]
    query = exp.Select()
    for dimension in cte.dimensions:
        query = query.select(
            exp.alias_(
                exp.column(
                    dimension.field.name,
                    table=context.sql_alias(dimension.entity),
                ),
                dimension.output_alias,
            )
        )
    for dimension in cte.null_dimensions:
        query = query.select(exp.alias_(exp.Null(), dimension.output_alias))
    for measure in cte.measures:
        query = query.select(
            exp.alias_(
                _aggregate(
                    measure.measure.aggregation,
                    exp.column(
                        measure.field.name,
                        table=context.sql_alias(measure.entity),
                    ),
                ),
                measure.output_alias,
            )
        )

    query = query.from_(_table(base_entity, context.sql_alias(base_entity)))
    for step in cte.steps:
        query = query.join(_join(step, context))

    where = _where([build_condition(predicate, context) for predicate in cte.filters])
    if where is not None:
        query = query.where(where)

    if cte.dimensions:
        query = query.group_by(
            *[
                exp.column(
                    dimension.field.name,
                    table=context.sql_alias(dimension.entity),
                )
                for dimension in cte.dimensions
            ]
        )
    return exp.CTE(
        this=query,
        alias=exp.TableAlias(this=exp.to_identifier(cte.name)),
    )


def _merge_condition(
    left: str, right: str, dimensions: tuple[ResolvedDimension, ...]
) -> exp.Expression:
    """Return the null-safe equality of the dimension columns of two CTEs."""
    condition: Any = None
    for dimension in dimensions:
        equality = exp.NullSafeEQ(
            this=exp.column(dimension.output_alias, table=left),
            expression=exp.column(dimension.output_alias, table=right),
        )
        condition = equality if condition is None else exp.and_(condition, equality)
    if condition is None:
        raise ValueError("A merge requires at least one dimension")
    return cast(exp.Expression, condition)


def build_merge(plan: MergePlan, context: CompileContext) -> exp.Select:
    """Build the main query that merges CTEs by dimension.

    Every dimension is coalesced across the CTEs, including the CTEs that could
    only provide it as NULL, and every measure is read from the CTE that
    aggregates it.

    Args:
        plan: Merge plan with the full dimension set and the CTEs to combine.
        context: Compilation state used for SQL aliases and parameters.

    Returns:
        A sqlglot SELECT expression with all CTEs attached.
    """
    statements = {cte.name: build_cte(cte, context) for cte in plan.ctes}
    first, rest = plan.ctes[0], plan.ctes[1:]

    query = exp.Select()
    for dimension in plan.dimensions:
        columns = [
            exp.column(dimension.output_alias, table=cte.name) for cte in plan.ctes
        ]
        coalesced = exp.Coalesce(this=columns[0], expressions=columns[1:])
        query = query.select(exp.alias_(coalesced, dimension.output_alias))
    for cte in plan.ctes:
        for measure in cte.measures:
            query = query.select(
                exp.alias_(
                    exp.column(measure.output_alias, table=cte.name),
                    measure.output_alias,
                )
            )

    query = query.from_(exp.to_table(first.name))
    for cte in rest:
        query = query.join(
            exp.Join(
                this=exp.to_table(cte.name),
                kind="FULL OUTER",
                on=_merge_condition(first.name, cte.name, plan.dimensions),
            )
        )

    for cte in plan.ctes:
        query = query.with_(cte.name, as_=statements[cte.name].this)
    return _apply_order_and_limit(query, plan.order_terms, plan.row_limit, context)
