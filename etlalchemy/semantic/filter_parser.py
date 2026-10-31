"""Parse filter expressions into Predicate nodes.

The filter DSL is a small SQL-like boolean language parsed with lark. It
supports comparisons over fully qualified fields (``alias.field``), literal
lists, ranges, NULL checks, LIKE patterns, parenthesised groups and ``NOT``:

* ``field = value`` with ``=``, ``!=``, ``<>``, ``<``, ``<=``, ``>``, ``>=``;
* ``field op field`` for field-to-field comparisons;
* ``field [NOT] IN (literal, ...)``;
* ``field [NOT] BETWEEN literal AND literal``;
* ``field IS [NOT] NULL``;
* ``field [NOT] LIKE pattern``;
* ``NOT expr`` and ``( expr )``;
* ``AND`` binds tighter than ``OR``; keywords are case-insensitive;
* literals are single- or double-quoted strings (doubled quotes escape),
  integers, floats, ``TRUE``, ``FALSE`` and ``NULL``.

Bare field names are rejected with a hint to use ``alias.field``. The parser
only builds the Predicate AST: it never evaluates the expression and never
uses ``eval`` or sqlglot. Parse failures raise ``ValueError`` naming the
position and quoting the surrounding text.
"""

from __future__ import annotations

from typing import Any, cast

from lark import Lark, Token, Transformer, exceptions

from etlalchemy.semantic.expression import (
    Between,
    Comparison,
    FieldComparison,
    FieldRef,
    In,
    IsNull,
    Like,
    Literal,
    Logical,
    Not,
    Predicate,
)

#: Grammar of the filter DSL. Keywords are matched case-insensitively and the
#: bare-identifier rule excludes them, so a field always needs ``alias.field``.
_GRAMMAR = (
    r"""
?start: filter_expr

?filter_expr: or_expr

?or_expr: and_expr (OR and_expr)*
?and_expr: unary_expr (AND unary_expr)*
?unary_expr: NOT unary_expr
           | parenthesized
           | predicate

parenthesized: "(" filter_expr ")"

?predicate: field NOT IN "(" literal_list ")"        -> not_in
          | field IN "(" literal_list ")"            -> in_list
          | field NOT BETWEEN literal AND literal    -> not_between
          | field BETWEEN literal AND literal        -> between
          | field IS NOT NULL                        -> not_null
          | field IS NULL                            -> is_null
          | field NOT LIKE literal                   -> not_like
          | field LIKE literal                       -> like
          | field comp_op field                      -> field_comparison
          | field comp_op literal                    -> comparison

comp_op: EQ | NEQ | LT | LTE | GT | GTE

literal_list: literal ("," literal)*

literal: STRING | NUMBER | TRUE | FALSE | NULL

field: FIELD | BARE

EQ: "="
NEQ: "!=" | "<>"
LT: "<"
LTE.2: "<="
GT: ">"
GTE.2: ">="
AND: /(?i:and)(?![A-Za-z0-9_])/
OR: /(?i:or)(?![A-Za-z0-9_])/
NOT: /(?i:not)(?![A-Za-z0-9_])/
IN: /(?i:in)(?![A-Za-z0-9_])/
BETWEEN: /(?i:between)(?![A-Za-z0-9_])/
IS: /(?i:is)(?![A-Za-z0-9_])/
LIKE: /(?i:like)(?![A-Za-z0-9_])/
TRUE: /(?i:true)(?![A-Za-z0-9_])/
FALSE: /(?i:false)(?![A-Za-z0-9_])/
NULL: /(?i:null)(?![A-Za-z0-9_])/
FIELD: /[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*/
"""
    # A bare identifier never shadows a keyword, so keyword matching stays
    # unambiguous in a dynamic lexer.
    r"""BARE: /(?!(?i:and|or|not|in|between|is|like|true|false|null)"""
    r"""(?![A-Za-z0-9_]))[A-Za-z_][A-Za-z0-9_]*/
"""
    r"""STRING: /'(?:[^']|'')*'|"(?:[^"]|"")*"/
NUMBER: /-?\d+(?:\.\d+)?/
%ignore /[ \t\r\n]+/
"""
)

#: Parser shared by every call; the grammar is small, so building it once at
#: import time is cheaper than per-call construction.
_PARSER = Lark(_GRAMMAR, parser="earley", start="start")

#: Characters of context quoted before and after a parse error.
_ERROR_CONTEXT = 12

#: Keywords kept in the parse tree only to mark an optional negation.
#: Keyword tokens dropped from rule children, including the NULL of IS NULL.
_KEYWORDS = frozenset(
    {"AND", "OR", "NOT", "IN", "BETWEEN", "IS", "LIKE", "NULL", "TRUE", "FALSE"}
)


def _values(items: list[Any]) -> list[Any]:
    """Drop the keyword tokens so a rule only sees its semantic children."""
    return [
        item
        for item in items
        if not (isinstance(item, Token) and item.type in _KEYWORDS)
    ]


def _context(text: str, position: int) -> str:
    """Return the text around ``position`` with a caret under the error."""
    start = max(position - _ERROR_CONTEXT, 0)
    end = min(position + _ERROR_CONTEXT, len(text))
    return f"\n  {text[start:end]}\n  {' ' * (position - start)}^"


def _literal(token: Token) -> Literal:
    """Convert one literal token into a Literal node."""
    text = str(token)
    if token.type == "STRING":
        quote = text[0]
        return Literal(text[1:-1].replace(quote * 2, quote))
    if token.type == "NUMBER":
        return Literal(float(text) if "." in text else int(text))
    keyword = text.upper()
    if keyword == "TRUE":
        return Literal(True)
    if keyword == "FALSE":
        return Literal(False)
    return Literal(None)


def _logical(operator: str, operands: list[Any]) -> Predicate:
    """Combine operands with one boolean operator, collapsing single chains."""
    if len(operands) == 1:
        return cast(Predicate, operands[0])
    return Logical(
        operator=operator,
        operands=tuple(cast(Predicate, operand) for operand in operands),
    )


class _FilterTransformer(Transformer[Token, object]):
    """Turn a lark parse tree into the Predicate AST."""

    def __init__(self, text: str) -> None:
        """Keep the original text so errors can quote their context."""
        super().__init__()
        self._text = text

    def field(self, items: list[Any]) -> FieldRef:
        """Build a FieldRef, rejecting bare names without an entity alias."""
        token = items[0]
        text = str(token)
        if token.type == "BARE":
            position = token.start_pos
            raise ValueError(
                f"Invalid filter at position {position}: field {text!r} must be "
                f"qualified; use alias.field{_context(self._text, position)}"
            )
        entity, _, name = text.partition(".")
        return FieldRef(entity=entity, name=name)

    def literal(self, items: list[Any]) -> Literal:
        """Convert the literal token into a Literal node."""
        return _literal(items[0])

    def literal_list(self, items: list[Any]) -> tuple[Literal, ...]:
        """Collect the comma separated literals of an IN list."""
        return tuple(cast(Literal, item) for item in items)

    def comp_op(self, items: list[Any]) -> str:
        """Return the comparison operator text."""
        return str(items[0])

    def or_expr(self, items: list[Any]) -> Predicate:
        """Fold the operands with OR."""
        return _logical("OR", _values(items))

    def and_expr(self, items: list[Any]) -> Predicate:
        """Fold the operands with AND."""
        return _logical("AND", _values(items))

    def unary_expr(self, items: list[Any]) -> Predicate:
        """Negate the operand of a NOT expression."""
        return Not(operand=cast(Predicate, _values(items)[0]))

    def parenthesized(self, items: list[Any]) -> Predicate:
        """Return the grouped expression unchanged."""
        return cast(Predicate, _values(items)[0])

    def in_list(self, items: list[Any]) -> Predicate:
        """Build an IN predicate."""
        field, values = _values(items)
        return In(field=field, values=values)

    def not_in(self, items: list[Any]) -> Predicate:
        """Build a negated IN predicate."""
        field, values = _values(items)
        return In(field=field, values=values, negated=True)

    def between(self, items: list[Any]) -> Predicate:
        """Build a BETWEEN predicate."""
        field, low, high = _values(items)
        return Between(field=field, low=low, high=high)

    def not_between(self, items: list[Any]) -> Predicate:
        """Build a negated BETWEEN predicate."""
        field, low, high = _values(items)
        return Between(field=field, low=low, high=high, negated=True)

    def is_null(self, items: list[Any]) -> Predicate:
        """Build an IS NULL predicate."""
        field = _values(items)[0]
        return IsNull(field=field)

    def not_null(self, items: list[Any]) -> Predicate:
        """Build an IS NOT NULL predicate."""
        field = _values(items)[0]
        return IsNull(field=field, negated=True)

    def like(self, items: list[Any]) -> Predicate:
        """Build a LIKE predicate."""
        field, pattern = _values(items)
        return Like(field=field, pattern=pattern)

    def not_like(self, items: list[Any]) -> Predicate:
        """Build a negated LIKE predicate."""
        field, pattern = _values(items)
        return Like(field=field, pattern=pattern, negated=True)

    def comparison(self, items: list[Any]) -> Predicate:
        """Build a field-to-literal comparison."""
        field, operator, value = _values(items)
        return Comparison(field=field, operator=operator, value=value)

    def field_comparison(self, items: list[Any]) -> Predicate:
        """Build a field-to-field comparison."""
        left, operator, right = _values(items)
        return FieldComparison(left=left, operator=operator, right=right)


def _syntax_error(exc: exceptions.UnexpectedInput, text: str) -> ValueError:
    """Translate a lark parse error into a ValueError with context."""
    position = getattr(exc, "pos_in_stream", None)
    if not isinstance(position, int) or position < 0:
        position = len(text)
    detail = str(exc).strip().splitlines()[0]
    return ValueError(
        f"Invalid filter at position {position}: {detail}{_context(text, position)}"
    )


def parse_filter(text: str) -> Predicate:
    """Parse a filter expression into a Predicate AST.

    Args:
        text: Filter expression, for example
            ``"(orders.status = 'paid' OR orders.status = 'shipped') AND
            orders.amount BETWEEN 100 AND 500"``.

    Returns:
        The root Predicate node of the expression.

    Raises:
        ValueError: If the expression is empty, a field is not written as
            ``alias.field``, or the syntax is invalid. Syntax errors name the
            position and quote the surrounding text.
    """
    expression = text.strip()
    if not expression:
        raise ValueError("Invalid filter at position 0: empty filter expression")
    try:
        tree = _PARSER.parse(expression)
    except exceptions.UnexpectedInput as exc:
        raise _syntax_error(exc, expression) from None
    try:
        result = _FilterTransformer(expression).transform(tree)
    except exceptions.VisitError as exc:
        if isinstance(exc.orig_exc, ValueError):
            raise exc.orig_exc from None
        raise ValueError(f"Invalid filter: {exc.orig_exc}") from None
    return cast(Predicate, result)


__all__ = ["parse_filter"]
