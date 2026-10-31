"""Format SQL text without any knowledge of the semantic model.

``format_sql`` parses a statement with sqlglot, applies the requested
identifier casing and renders it again with a readable layout. It is a pure
utility module: it imports sqlglot only, so it can be used on any SQL text that
sqlglot understands.

``format_sql`` always formats. It parses and re-renders the statement, so the
comments of the input SQL and part of its original whitespace are lost: this is
a "parse and lay out again" tool, not a comment-preserving formatter. Call
sqlglot directly with ``sql(pretty=False)`` when a single-line statement is
needed.

Layout rules on top of sqlglot's pretty printer, with ``indent_width`` spaces
per level (2 by default):

* a ``FROM`` clause that shares a line with other content moves to its own
  line;
* every ``JOIN`` is indented one level, and its ``ON``/``USING`` condition one
  level further;
* ``ORDER BY`` sits on its own line and every ordering item is indented one
  level;
* ``LIMIT`` sits on its own line, with its value on the same line;
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

#: Lines that start a clause and therefore end an ORDER BY item list.
_CLAUSE_PREFIXES = (
    ")",
    "EXCEPT ",
    "FROM ",
    "GROUP BY",
    "HAVING ",
    "INTERSECT ",
    "LIMIT ",
    "ORDER BY",
    "SELECT ",
    "UNION ",
    "WHERE ",
    "WITH ",
)


def format_sql(
    sql: str,
    dialect: str = "databricks",
    identifier_case: str = "upper",
    indent_width: int = 2,
) -> str:
    """Format one SQL statement for readability.

    Re-rendering drops the comments of the input SQL, because the statement is
    parsed and laid out again rather than edited in place.

    Args:
        sql: SQL text to format.
        dialect: Dialect sqlglot parses and renders the statement with.
        identifier_case: One of ``"preserve"``, ``"upper"`` or ``"lower"``.
            The case applies to every identifier, including table names,
            column names, CTE names and output aliases; ``"preserve"`` keeps
            the casing of ``sql``.
        indent_width: Number of spaces per indentation level, ``2`` by
            default. JOIN conditions and ORDER BY items each take one extra
            level.

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

    raw_sql = expression.sql(
        dialect=dialect,
        pretty=True,
        pad=indent_width,
        indent=indent_width,
        identify=False,
        comments=False,
    )
    formatted = _format_from_and_joins(raw_sql, indent_width)
    formatted = _format_order_and_limit(formatted, indent_width)
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


def _format_order_and_limit(sql: str, indent_width: int) -> str:
    """Put ORDER BY and LIMIT on their own lines and indent the sort items."""
    indent = " " * indent_width
    lines = sql.splitlines()
    formatted: list[str] = []
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        order_at = stripped.find("ORDER BY")
        if order_at > 0:
            prefix = stripped[:order_at].rstrip()
            if prefix:
                formatted.append(prefix)
            stripped = stripped[order_at:]
        if stripped.startswith("ORDER BY"):
            formatted.append("ORDER BY")
            remainder = stripped[len("ORDER BY") :].strip()
            limit_tail = ""
            limit_at = remainder.find(" LIMIT ")
            if limit_at >= 0:
                limit_tail = remainder[limit_at + 1 :].strip()
                remainder = remainder[:limit_at].rstrip()
            items = _split_top_level(remainder.rstrip(","))
            index += 1
            while index < len(lines):
                candidate = lines[index].strip()
                if not candidate or _starts_new_clause(candidate):
                    break
                items.extend(_split_top_level(candidate.rstrip(",")))
                index += 1
            for position, item in enumerate(items):
                if not item.strip():
                    continue
                separator = "," if position < len(items) - 1 else ""
                formatted.append(f"{indent}{item.strip()}{separator}")
            if limit_tail:
                formatted.append(limit_tail)
            continue
        limit_at = stripped.find("LIMIT ")
        if limit_at > 0:
            prefix = stripped[:limit_at].rstrip()
            if prefix:
                formatted.append(prefix)
            formatted.append(stripped[limit_at:])
            index += 1
            continue
        formatted.append(lines[index])
        index += 1
    return "\n".join(formatted)


def _starts_new_clause(text: str) -> bool:
    """Return whether a line starts a clause that ends an ORDER BY list."""
    return text.startswith(_CLAUSE_PREFIXES)


def _split_top_level(text: str) -> list[str]:
    """Split a comma separated list on the commas outside parentheses."""
    items: list[str] = []
    current: list[str] = []
    depth = 0
    for character in text:
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        if character == "," and depth == 0:
            items.append("".join(current))
            current = []
            continue
        current.append(character)
    if current:
        items.append("".join(current))
    return items


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
        body = _format_body(cte.this, dialect, indent_width, indent)
        if index == 0:
            keyword = "WITH RECURSIVE" if with_clause.args.get("recursive") else "WITH"
            blocks.append(f"{keyword} {cte.alias} AS (\n{body}\n)")
        else:
            blocks.append(f"{cte.alias} AS (\n{body}\n)")
    with_sql = ",\n".join(blocks)

    main = expression.copy()
    main.set("with_", None)
    main_sql = _format_body(main, dialect, indent_width, "")
    return f"{with_sql}\n{main_sql}"


def _format_body(
    expression: exp.Expression,
    dialect: str,
    indent_width: int,
    indent: str,
) -> str:
    """Render one query body and apply the join and ORDER BY layout rules."""
    body = expression.sql(
        dialect=dialect,
        pretty=True,
        pad=indent_width,
        indent=indent_width,
        identify=False,
        comments=False,
    )
    body = _format_from_and_joins(body, indent_width)
    body = _format_order_and_limit(body, indent_width)
    return textwrap.indent(body, indent)


__all__ = ["IDENTIFIER_CASES", "format_sql"]
