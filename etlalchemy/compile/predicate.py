"""Translate predicate trees into sqlglot condition expressions.

``Comparison`` and ``FieldComparison`` map their operator onto the matching
sqlglot comparison class, ``In``, ``Between``, ``IsNull`` and ``Like`` build
their sqlglot node, ``Not`` negates its operand, and ``Logical`` folds its
operands with AND/OR. sqlglot's condition nodes have no ``negated`` argument,
so negated predicates are wrapped in ``exp.Not``.
"""

from __future__ import annotations

from typing import Any, cast

from sqlglot import exp

from etlalchemy.compile.context import CompileContext
from etlalchemy.compile.resolve import resolve_field
from etlalchemy.semantic.expression import (
    Between,
    Comparison,
    FieldComparison,
    FieldRef,
    In,
    IsNull,
    Like,
    Not,
    Predicate,
)

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
        The value converted to its sqlglot literal node when
        ``context.inline_literals`` is set, otherwise a placeholder bound to
        the value.
    """
    if context.inline_literals:
        return cast(exp.Expression, exp.convert(value))
    name = context.add_parameter(value)
    return exp.Placeholder(this=name)


def _column(ref: FieldRef, context: CompileContext) -> exp.Column:
    """Return the aliased column of one field reference."""
    entity, field = resolve_field(ref, context)
    return exp.column(field.name, table=context.sql_alias(entity))


def _comparison(
    operator: str,
    left: exp.Expression,
    right: exp.Expression,
) -> exp.Expression:
    """Build one comparison node from the operator table.

    Raises:
        ValueError: If the operator is not supported.
    """
    builder = _COMPARISONS.get(operator)
    if builder is None:
        raise ValueError(f"Unsupported comparison operator {operator!r}")
    return cast(exp.Expression, builder(this=left, expression=right))


def _negate(node: exp.Expression, negated: bool) -> exp.Expression:
    """Wrap a condition in NOT when the node asks for the negated form."""
    return exp.Not(this=node) if negated else node


def build_condition(predicate: Predicate, context: CompileContext) -> exp.Expression:
    """Build a sqlglot condition for a predicate node.

    Literals are inlined as SQL literals when ``context.inline_literals`` is
    set and become bound parameters otherwise. ``IN`` lists bind or inline
    every value, and negated nodes are wrapped in ``exp.Not`` because sqlglot's
    condition nodes take no ``negated`` argument.

    Args:
        predicate: Predicate node from the query.
        context: Compilation state that collects the parameters.

    Returns:
        A sqlglot condition expression.

    Raises:
        ValueError: If a comparison operator is not supported.
    """
    if isinstance(predicate, Comparison):
        return _comparison(
            predicate.operator,
            _column(predicate.field, context),
            build_literal(predicate.value.value, context),
        )
    if isinstance(predicate, FieldComparison):
        return _comparison(
            predicate.operator,
            _column(predicate.left, context),
            _column(predicate.right, context),
        )
    if isinstance(predicate, In):
        in_node = exp.In(
            this=_column(predicate.field, context),
            expressions=[
                build_literal(value.value, context) for value in predicate.values
            ],
        )
        return _negate(in_node, predicate.negated)
    if isinstance(predicate, Between):
        between = exp.Between(
            this=_column(predicate.field, context),
            low=build_literal(predicate.low.value, context),
            high=build_literal(predicate.high.value, context),
        )
        return _negate(between, predicate.negated)
    if isinstance(predicate, IsNull):
        is_null = exp.Is(
            this=_column(predicate.field, context),
            expression=exp.Null(),
        )
        return _negate(is_null, predicate.negated)
    if isinstance(predicate, Like):
        like = exp.Like(
            this=_column(predicate.field, context),
            expression=build_literal(predicate.pattern.value, context),
        )
        return _negate(like, predicate.negated)
    if isinstance(predicate, Not):
        inner = build_condition(predicate.operand, context)
        # A bare NOT over AND/OR would lose its grouping without parentheses.
        negated: exp.Expression = (
            exp.Paren(this=inner) if isinstance(inner, exp.Connector) else inner
        )
        return exp.Not(this=negated)

    joiner = exp.and_ if predicate.operator == "AND" else exp.or_
    operands = [build_condition(operand, context) for operand in predicate.operands]
    condition: Any = operands[0]
    for operand in operands[1:]:
        condition = joiner(condition, operand)
    return cast(exp.Expression, condition)
