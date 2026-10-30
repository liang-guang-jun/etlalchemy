"""Translate predicate trees into sqlglot condition expressions."""

from __future__ import annotations

from typing import Any, cast

from sqlglot import exp

from etlalchemy.compile.context import CompileContext
from etlalchemy.compile.resolve import resolve_field
from etlalchemy.semantic.expression import Comparison, Predicate

_COMPARISONS: dict[str, Any] = {
    "=": exp.EQ,
    "!=": exp.NEQ,
    "<>": exp.NEQ,
    "<": exp.LT,
    "<=": exp.LTE,
    ">": exp.GT,
    ">=": exp.GTE,
}


def build_literal(value: object, context: CompileContext) -> exp.Expression:
    """Build a sqlglot literal or a bound placeholder for a value.

    Args:
        value: Python value taken from a predicate literal.
        context: Compilation state that collects bound parameters.

    Returns:
        A placeholder when ``context.bind_literals`` is set, otherwise the
        value converted to its sqlglot literal node.
    """
    if context.bind_literals:
        name = context.add_parameter(value)
        return exp.Placeholder(this=name)
    return cast(exp.Expression, exp.convert(value))


def build_condition(predicate: Predicate, context: CompileContext) -> exp.Expression:
    """Build a sqlglot condition for a predicate node.

    Literals become bound parameters when ``context.bind_literals`` is set and
    are inlined as SQL literals otherwise.

    Args:
        predicate: Predicate node from the query.
        context: Compilation state that collects the parameters.

    Returns:
        A sqlglot condition expression.

    Raises:
        ValueError: If a comparison operator is not supported.
    """
    if isinstance(predicate, Comparison):
        entity, field = resolve_field(predicate.field, context)
        builder = _COMPARISONS.get(predicate.operator)
        if builder is None:
            raise ValueError(f"Unsupported comparison operator {predicate.operator!r}")
        placeholder = build_literal(predicate.value.value, context)
        comparison: Any = builder(
            this=exp.column(field.name, table=context.sql_alias(entity)),
            expression=placeholder,
        )
        return cast(exp.Expression, comparison)

    joiner = exp.and_ if predicate.operator == "AND" else exp.or_
    operands = [build_condition(operand, context) for operand in predicate.operands]
    condition: Any = operands[0]
    for operand in operands[1:]:
        condition = joiner(condition, operand)
    return cast(exp.Expression, condition)
