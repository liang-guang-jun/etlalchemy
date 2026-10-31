"""Tests for the lark based filter DSL parser."""

from __future__ import annotations

import pytest
from etlalchemy.semantic import (
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
)
from etlalchemy.semantic.filter_parser import parse_filter


def test_comparison_parses_field_and_literal() -> None:
    """A single comparison becomes a Comparison node."""
    assert parse_filter("orders.status = 'paid'") == Comparison(
        field=FieldRef("orders", "status"),
        operator="=",
        value=Literal("paid"),
    )


def test_field_to_field_comparison() -> None:
    """A comparison between two fields becomes a FieldComparison."""
    assert parse_filter("orders.amount > refunds.amount") == FieldComparison(
        left=FieldRef("orders", "amount"),
        operator=">",
        right=FieldRef("refunds", "amount"),
    )


def test_and_binds_tighter_than_or() -> None:
    """AND groups before OR, so the OR keeps two operands."""
    predicate = parse_filter("a.x = 1 OR b.y = 2 AND c.z = 3")

    assert isinstance(predicate, Logical)
    assert predicate.operator == "OR"
    first, second = predicate.operands
    assert isinstance(first, Comparison)
    assert isinstance(second, Logical)
    assert second.operator == "AND"


def test_parentheses_group_the_expression() -> None:
    """Parentheses override the AND/OR precedence."""
    predicate = parse_filter("a.x = 1 AND (b.y = 2 OR c.z = 3)")

    assert isinstance(predicate, Logical)
    assert predicate.operator == "AND"
    _, second = predicate.operands
    assert isinstance(second, Logical)
    assert second.operator == "OR"


def test_not_negates_a_predicate() -> None:
    """NOT wraps the following predicate."""
    predicate = parse_filter("NOT a.x = 1")

    assert isinstance(predicate, Not)
    assert isinstance(predicate.operand, Comparison)


def test_not_keeps_a_grouped_or() -> None:
    """NOT over a parenthesized group negates the whole group."""
    predicate = parse_filter("NOT (a.x = 1 OR b.y = 2)")

    assert isinstance(predicate, Not)
    assert isinstance(predicate.operand, Logical)
    assert predicate.operand.operator == "OR"


def test_in_list() -> None:
    """IN keeps every literal in declaration order."""
    assert parse_filter("orders.status IN ('paid', 'shipped')") == In(
        field=FieldRef("orders", "status"),
        values=(Literal("paid"), Literal("shipped")),
    )


def test_not_in_list() -> None:
    """NOT IN sets the negated flag."""
    predicate = parse_filter("orders.status NOT IN ('test')")

    assert isinstance(predicate, In)
    assert predicate.negated is True
    assert predicate.values == (Literal("test"),)


def test_between() -> None:
    """BETWEEN stores its inclusive bounds."""
    assert parse_filter("orders.amount BETWEEN 100 AND 500") == Between(
        field=FieldRef("orders", "amount"),
        low=Literal(100),
        high=Literal(500),
    )


def test_not_between() -> None:
    """NOT BETWEEN sets the negated flag."""
    predicate = parse_filter("orders.amount NOT BETWEEN 1 AND 2")

    assert isinstance(predicate, Between)
    assert predicate.negated is True


def test_is_null() -> None:
    """IS NULL produces an IsNull node."""
    assert parse_filter("users.region IS NULL") == IsNull(
        field=FieldRef("users", "region")
    )


def test_is_not_null() -> None:
    """IS NOT NULL sets the negated flag."""
    predicate = parse_filter("users.region IS NOT NULL")

    assert isinstance(predicate, IsNull)
    assert predicate.negated is True


def test_like() -> None:
    """LIKE keeps the pattern as a literal."""
    assert parse_filter("orders.status LIKE 'p%'") == Like(
        field=FieldRef("orders", "status"),
        pattern=Literal("p%"),
    )


def test_not_like() -> None:
    """NOT LIKE sets the negated flag."""
    predicate = parse_filter("orders.status NOT LIKE 'p%'")

    assert isinstance(predicate, Like)
    assert predicate.negated is True


def test_boolean_and_null_literals() -> None:
    """TRUE, FALSE and NULL become typed literals."""
    predicate = parse_filter("a.x = TRUE AND b.y = NULL")

    assert isinstance(predicate, Logical)
    first, second = predicate.operands
    assert isinstance(first, Comparison)
    assert first.value == Literal(True)
    assert isinstance(second, Comparison)
    assert second.value == Literal(None)


def test_numeric_literals_are_typed() -> None:
    """Integers and floats keep their Python type."""
    predicate = parse_filter("a.x = 1.5")

    assert isinstance(predicate, Comparison)
    assert predicate.value == Literal(1.5)


def test_keywords_are_case_insensitive() -> None:
    """Lowercase keywords parse like their uppercase form."""
    predicate = parse_filter("a.x = 1 and b.y = 2")

    assert isinstance(predicate, Logical)
    assert predicate.operator == "AND"


def test_strings_unescape_doubled_quotes() -> None:
    """A doubled quote inside a string is one quote."""
    predicate = parse_filter("a.x = 'it''s'")

    assert isinstance(predicate, Comparison)
    assert predicate.value == Literal("it's")


def test_bare_field_names_are_rejected() -> None:
    """A field without its entity alias gets a hint."""
    with pytest.raises(ValueError, match="use alias.field"):
        parse_filter("status = 'paid'")


def test_function_calls_are_rejected() -> None:
    """The DSL has no function calls."""
    with pytest.raises(ValueError, match="Invalid filter at position"):
        parse_filter("SUBSTR(orders.status, 1, 1) = 'p'")


def test_syntax_errors_name_the_position() -> None:
    """A truncated expression reports its position."""
    with pytest.raises(ValueError, match="Invalid filter at position"):
        parse_filter("orders.status = ")


def test_empty_filter_is_rejected() -> None:
    """An empty expression is an error, not an empty predicate."""
    with pytest.raises(ValueError, match="empty filter expression"):
        parse_filter("   ")
