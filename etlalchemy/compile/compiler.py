"""Entry point that turns a semantic query into dialect SQL and parameters."""

from __future__ import annotations

from etlalchemy.compile.builder import build_merge, build_select
from etlalchemy.compile.context import CompileContext
from etlalchemy.compile.plan import (
    group_measures_by_entity,
    plan_ctes,
    plan_joins,
    plan_merge,
)
from etlalchemy.compile.resolve import resolve_query
from etlalchemy.compile.routes import select_edges
from etlalchemy.semantic.expression import Query
from etlalchemy.semantic.join import ExpressionJoin
from etlalchemy.semantic.model import SemanticModel
from etlalchemy.semantic.relationship import SemanticRelationship

_UNREACHABLE_DIMENSIONS = frozenset({"error", "null"})


def _warn_expression_joins(
    edges: tuple[SemanticRelationship, ...],
    context: CompileContext,
) -> None:
    """Warn about expression joins that cannot bind their literals."""
    if not context.bind_literals:
        return
    for relationship in edges:
        if isinstance(relationship.condition, ExpressionJoin):
            context.report.add_warning(
                "expression join does not bind literals; ensure the expression "
                f"is safe in relationship {relationship.name!r}"
            )


def compile_query(
    query: Query,
    model: SemanticModel,
    dialect: str = "postgres",
    *,
    bind_literals: bool = False,
    pretty: bool = True,
    unreachable_dimensions: str = "error",
    nulls_first: bool | None = None,
) -> tuple[str, list[object] | dict[str, object]]:
    """Compile a semantic query into dialect SQL and parameters.

    The compilation resolves the query references, selects the relationships it
    traverses, plans one CTE per fact entity, and renders either a single
    select or the CTE merge query for ``dialect``.

    Args:
        query: Semantic query to compile.
        model: Model used to resolve entities and measures.
        dialect: Target SQL dialect understood by sqlglot.
        bind_literals: When True, literal values become bound parameters and
            are returned separately; when False (default) they are inlined
            into the SQL text. Inlining is convenient for debugging and for
            trusted values, but it must not be used with untrusted input: it
            leaks values into SQL logs and defeats statement caching. Prefer
            ``bind_literals=True`` for anything user-supplied.
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

    Returns:
        ``(sql, params)``. With ``bind_literals`` set, ``params`` is a dict
        keyed by placeholder name (or a positional list when the dialect uses
        positional placeholders); drivers that only accept positional
        arguments need the caller to convert the dict themselves. Without
        binding, ``params`` is an empty list.

    Raises:
        ValueError: If ``unreachable_dimensions`` is not ``"error"`` or
            ``"null"``, or a query reference cannot be planned.
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
        bind_literals=bind_literals,
        unreachable_dimensions=unreachable_dimensions,
        nulls_first=nulls_first,
    )
    resolved = resolve_query(query, context)
    edges = select_edges(resolved, context)
    _warn_expression_joins(edges, context)

    grouped = group_measures_by_entity(resolved)
    if len(grouped) > 1:
        ctes = plan_ctes(
            resolved, grouped, edges, model.registry, unreachable_dimensions
        )
        context.report.cte_count = len(ctes)
        for cte in ctes:
            for dimension in cte.null_dimensions:
                context.report.add_unreachable_dimension(
                    f"Dimension {dimension.output_alias!r} is NULL for entity "
                    f"{cte.entity_alias!r}"
                )
        statement = build_merge(plan_merge(resolved, ctes), context)
    else:
        statement = build_select(plan_joins(resolved, edges, context), context)

    sql = statement.sql(dialect=dialect, pretty=pretty)
    if not bind_literals:
        return sql, []
    return sql, dict(context.parameters)
