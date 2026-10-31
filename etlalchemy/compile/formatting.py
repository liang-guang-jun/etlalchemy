"""Format SQL text without any knowledge of the semantic model.

``format_sql`` parses a statement with sqlglot, applies the requested
identifier casing and renders it again with a readable layout. It is a pure
utility module: it imports sqlglot only, so it can be used on any SQL text that
sqlglot understands.

Layout rules on top of sqlglot's pretty printer:

* a ``FROM`` clause that shares a line with other content moves to its own
  line;
* every ``JOIN`` is indented one level, and its ``ON``/``USING`` condition one
  level further;
* every CTE body is indented one level and each CTE starts on its own line.
"""

from __future__ import annotations

import re
import textwrap
from typing import Any, cast

import sqlglot
from sqlglot import exp

#: Identifier casings accepted by :func:`format_sql`.
IDENTIFIER_CASES = ("preserve", "upper", "lower")

#: Prefixes of the join clauses that are indented below the FROM clause.
_JOIN_PREFIXES = (
    "CROSS JOIN",
    "FULL OUTER JOIN",
    "FULL JOIN",
    "INNER JOIN",
    "LEFT OUTER JOIN",
    "LEFT JOIN",
    "RIGHT OUTER JOIN",
    "RIGHT JOIN",
    "JOIN",
)

#: Condition keywords that sit one level below their join.
_CONDITION_PREFIXES = ("ON ", "USING ")

#: A FROM keyword surrounded by whitespace.
_FROM_PATTERN = re.compile(r"\bFROM\b")


def format_sql(
    sql: str,
    dialect: str = "databricks",
    identifier_case: str = "upper",
    indent_width: int = 2,
    pretty: bool = True,
) -> str:
    """Format one SQL statement for readability.

    Args:
        sql: SQL text to format.
        dialect: Dialect sqlglot parses and renders the statement with.
        identifier_case: One of ``"preserve"``, ``"upper"`` or ``"lower"``;
            ``"preserve"`` keeps the identifier casing of ``sql``.
        indent_width: Number of spaces per indentation level.
        pretty: When False the statement is rendered on a single line and the
            layout rules are skipped.

    Returns:
        The formatted SQL text.

    Raises:
        ValueError: If ``identifier_case`` is not one of
            :data:`IDENTIFIER_CASES`.
    """
    if identifier_case not in IDENTIFIER_CASES:
        expected = ", ".join(IDENTIFIER_CASES)
        raise ValueError(
            f"Unsupported identifier_case {identifier_case!r}; expected one of "
            f"{expected}"
        )

    expression = cast(exp.Expression, sqlglot.parse_one(sql, read=dialect))
    _apply_identifier_case(expression, identifier_case)

    if not pretty:
        return expression.sql(dialect=dialect, pretty=False)

    raw_sql = expression.sql(
        dialect=dialect,
        pretty=True,
        pad=indent_width,
        indent=indent_width,
        identify=False,
    )
    formatted = _format_from_and_joins(raw_sql, indent_width)
    return _format_ctes(formatted, expression, dialect, indent_width)


def _apply_identifier_case(expression: exp.Expression, identifier_case: str) -> None:
    """Rewrite every identifier of the statement to the requested casing."""
    if identifier_case == "preserve":
        return
    transform = str.upper if identifier_case == "upper" else str.lower
    for identifier in expression.find_all(exp.Identifier):
        identifier.set("this", transform(identifier.this))


def _format_from_and_joins(sql: str, indent_width: int) -> str:
    """Put FROM on its own line and indent every JOIN and its condition."""
    indent = " " * indent_width
    formatted: list[str] = []
    in_join = False
    for line in sql.splitlines():
        stripped = line.strip()
        if not stripped:
            formatted.append(line)
            continue
        if stripped.startswith(_JOIN_PREFIXES):
            formatted.append(f"{indent}{stripped}")
            in_join = True
            continue
        if in_join and stripped.startswith(_CONDITION_PREFIXES):
            formatted.append(f"{indent}{indent}{stripped}")
            continue
        in_join = False
        formatted.append(_from_on_its_own_line(line))
    return "\n".join(formatted)


def _from_on_its_own_line(line: str) -> str:
    """Split a FROM clause that shares its line onto a line of its own."""
    stripped = line.lstrip()
    if not _FROM_PATTERN.search(line) or re.match(r"FROM\b", stripped):
        return line
    if "'" in line or '"' in line:
        return line
    before, separator, after = line.partition(" FROM ")
    if not separator or not before.strip():
        return line
    return f"{before.rstrip()}\nFROM {after}"


def _format_ctes(
    sql: str,
    expression: exp.Expression,
    dialect: str,
    indent_width: int,
) -> str:
    """Indent each CTE body and keep every CTE on its own line."""
    with_clause: Any = expression.args.get("with_")
    if with_clause is None:
        return sql
    indent = " " * indent_width
    blocks: list[str] = []
    for index, cte in enumerate(with_clause.expressions):
        body = cte.this.sql(
            dialect=dialect,
            pretty=True,
            pad=indent_width,
            indent=indent_width,
            identify=False,
        )
        body = _format_from_and_joins(body, indent_width)
        body = textwrap.indent(body, indent)
        if index == 0:
            keyword = "WITH RECURSIVE" if with_clause.args.get("recursive") else "WITH"
            blocks.append(f"{keyword} {cte.alias} AS (\n{body}\n)")
        else:
            blocks.append(f"{cte.alias} AS (\n{body}\n)")
    with_sql = ",\n".join(blocks)

    main = expression.copy()
    main.set("with_", None)
    main_sql = main.sql(
        dialect=dialect,
        pretty=True,
        pad=indent_width,
        indent=indent_width,
        identify=False,
    )
    return f"{with_sql}\n{_format_from_and_joins(main_sql, indent_width)}"


__all__ = ["IDENTIFIER_CASES", "format_sql"]
