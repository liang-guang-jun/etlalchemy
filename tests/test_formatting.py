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


def test_default_identifier_case_is_upper() -> None:
    """The formatter uppercases identifiers unless asked otherwise."""
    sql = format_sql("select * from users")

    assert "USERS" in sql
    assert "users" not in sql


def test_identifier_case_upper_applies_to_output_aliases() -> None:
    """The case applies to table names, columns and output aliases alike."""
    sql = format_sql("select amount as total from orders", identifier_case="upper")

    assert "AMOUNT AS TOTAL" in sql
    assert "FROM ORDERS" in sql


def test_identifier_case_lower() -> None:
    """Lower casing rewrites every identifier of the statement."""
    sql = format_sql("SELECT * FROM USERS", identifier_case="lower")

    assert "users" in sql
    assert "USERS" not in sql


def test_identifier_case_preserve_keeps_the_input_casing() -> None:
    """Preserve leaves the casing of the parsed identifiers alone."""
    sql = format_sql("select Amount as Total from Orders", identifier_case="preserve")

    assert "Amount AS Total" in sql
    assert "Orders" in sql


def test_joins_are_indented_with_their_conditions_one_level_deeper() -> None:
    """A JOIN sits one level below FROM and its ON condition one below that."""
    sql = format_sql(
        "select customers.region from orders "
        "join customers on orders.customer_id = customers.id",
        identifier_case="preserve",
    )
    lines = sql.splitlines()

    join_line = next(line for line in lines if "JOIN customers" in line)
    on_line = next(line for line in lines if line.strip().startswith("ON "))

    assert join_line.startswith("  JOIN customers")
    assert on_line.startswith("    ON orders.customer_id")


def test_order_by_items_and_limit_get_their_own_lines() -> None:
    """ORDER BY and LIMIT start new lines and the sort items are indented."""
    sql = format_sql(
        "select a, b from t order by a desc, b limit 10",
        identifier_case="preserve",
    )
    lines = sql.splitlines()

    index = lines.index("ORDER BY")
    assert lines[index + 1] == "  a DESC,"
    assert lines[index + 2] == "  b"
    assert lines[-1] == "LIMIT 10"


def test_default_indent_width_is_two() -> None:
    """The default indentation level is two spaces."""
    lines = format_sql("select a, b from t", identifier_case="preserve").splitlines()

    assert lines[1].startswith("  a")
    assert not lines[1].startswith("    ")


def test_cte_bodies_keep_their_order_by_and_limit_layout() -> None:
    """ORDER BY and LIMIT inside a CTE body follow the same rules."""
    sql = format_sql(
        "with a as (select x from t order by x desc limit 3) "
        "select * from a order by x limit 5",
        identifier_case="preserve",
    )
    lines = sql.splitlines()

    assert lines[0] == "WITH a AS ("
    assert "  ORDER BY" in lines
    assert "    x DESC" in lines
    assert "  LIMIT 3" in lines
    assert "LIMIT 5" in lines


def test_comments_are_dropped() -> None:
    """Re-rendering drops both leading and inline comments."""
    sql = format_sql(
        "-- pick rows\nselect a /* inline */ from t",
        identifier_case="preserve",
    )

    assert "pick rows" not in sql
    assert "inline" not in sql


def test_unknown_identifier_case_is_rejected() -> None:
    """Only preserve, upper and lower are accepted."""
    with pytest.raises(ValueError, match="Unsupported identifier_case 'title'"):
        format_sql("select 1", identifier_case="title")

    with pytest.raises(ValueError, match="preserve, upper, lower"):
        format_sql("select 1", identifier_case="title")


def test_format_sql_is_exported_from_the_package() -> None:
    """The formatter is reachable from the package root."""
    assert etlalchemy.format_sql is format_sql
