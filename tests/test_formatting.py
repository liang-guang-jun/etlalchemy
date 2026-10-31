"""Tests for the standalone SQL formatter."""

from __future__ import annotations

import etlalchemy
import pytest
from etlalchemy.compile.formatting import format_sql


def test_identifier_case_upper_puts_from_on_its_own_line() -> None:
    """Upper casing applies to identifiers and FROM starts a new line."""
    sql = format_sql("select * from users", identifier_case="upper")
    lines = sql.splitlines()

    assert lines[0] == "SELECT"
    assert "FROM USERS" in lines
    assert "users" not in sql


def test_identifier_case_lower() -> None:
    """Lower casing rewrites every identifier of the statement."""
    sql = format_sql("SELECT * FROM USERS", identifier_case="lower")

    assert "users" in sql
    assert "USERS" not in sql


def test_joins_are_indented_with_their_conditions_one_level_deeper() -> None:
    """A JOIN sits one level below FROM and its ON condition one below that."""
    sql = format_sql(
        "select customers.region from orders "
        "join customers on orders.customer_id = customers.id",
        indent_width=2,
    )
    lines = sql.splitlines()

    join_line = next(line for line in lines if "JOIN customers" in line)
    on_line = next(line for line in lines if line.strip().startswith("ON "))

    assert join_line.startswith("  JOIN customers")
    assert on_line.startswith("    ON orders.customer_id")


def test_ctes_get_indented_bodies_and_their_own_lines() -> None:
    """Each CTE starts on its own line and its body is indented."""
    sql = format_sql(
        "with a as (select 1 as x), b as (select 2 as y) "
        "select * from a join b on a.x = b.y"
    )
    lines = sql.splitlines()

    assert lines[0] == "WITH a AS ("
    assert "b AS (" in lines
    assert lines[1].startswith("    SELECT")
    assert lines[1] == "    SELECT"


def test_pretty_false_returns_a_single_line() -> None:
    """Compact output keeps the statement on one line."""
    sql = format_sql("select * from users", pretty=False)

    assert "\n" not in sql
    assert sql == "SELECT * FROM users"


def test_unknown_identifier_case_is_rejected() -> None:
    """Only preserve, upper and lower are accepted."""
    with pytest.raises(ValueError, match="Unsupported identifier_case 'title'"):
        format_sql("select 1", identifier_case="title")

    with pytest.raises(ValueError, match="preserve, upper, lower"):
        format_sql("select 1", identifier_case="title")


def test_format_sql_is_exported_from_the_package() -> None:
    """The formatter is reachable from the package root."""
    assert etlalchemy.format_sql is format_sql
