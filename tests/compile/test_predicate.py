"""Tests for compiling filter DSL predicates into sqlglot conditions."""

from __future__ import annotations

from uuid import UUID, uuid5

import pytest
from etlalchemy.compile.context import CompileContext
from etlalchemy.compile.predicate import build_condition
from etlalchemy.semantic import (
    Field,
    FieldCollection,
    FieldRef,
    Materialization,
    Measure,
    Query,
    Rowset,
    SemanticEntity,
    SemanticModel,
    SemanticRegistry,
    String,
    equi_join,
)
from etlalchemy.semantic.filter_parser import parse_filter
from sqlglot import exp

NAMESPACE = UUID("00000000-0000-0000-0000-000000000000")


def _squash(sql: str) -> str:
    """Collapse whitespace so assertions survive formatting."""
    return " ".join(sql.split())


def _entity(alias: str, *fields: str) -> SemanticEntity:
    """Build a string-only entity with a primary key."""
    rowset = Rowset(
        name=f"crm.{alias}",
        kind=Materialization.TABLE,
        fields={name: Field(name=name, data_type=String()) for name in fields},
        primary_key=["id"],
    )
    return SemanticEntity(id=uuid5(NAMESPACE, alias), alias=alias, relation=rowset)


def _model() -> SemanticModel:
    """Build a small model with two fact entities and one unused dimension."""
    orders = _entity("orders", "id", "amount", "status")
    refunds = _entity("refunds", "id", "amount")
    campaigns = _entity("campaigns", "id", "budget")
    registry = SemanticRegistry(
        entities={"orders": orders, "refunds": refunds, "campaigns": campaigns},
        relationships=[
            equi_join(
                name="orders_refunds",
                source=FieldCollection(orders, (orders.relation.fields["id"],)),
                target=FieldCollection(refunds, (refunds.relation.fields["id"],)),
            )
        ],
    )
    registry.measures["revenue"] = Measure(
        name="revenue", field=FieldRef(entity="orders", name="amount")
    )
    registry.measures["refund_total"] = Measure(
        name="refund_total", field=FieldRef(entity="refunds", name="amount")
    )
    return SemanticModel(name="crm", registry=registry)


def _context(**overrides: object) -> CompileContext:
    """Build a compile context for a model-independent predicate."""
    model = _model()
    return CompileContext(model=model, query=Query(), **overrides)  # type: ignore[arg-type]


def _condition(text: str, **overrides: object) -> exp.Expression:
    """Parse and compile one filter expression."""
    return build_condition(parse_filter(text), _context(**overrides))


def test_comparison_builds_an_equality() -> None:
    """A literal comparison maps onto exp.EQ."""
    node = _condition("orders.status = 'paid'")

    assert isinstance(node, exp.EQ)
    assert node.sql() == "orders.status = 'paid'"


def test_field_comparison_uses_both_aliases() -> None:
    """A field-to-field comparison renders two qualified columns."""
    node = _condition("orders.amount > refunds.amount")

    assert isinstance(node, exp.GT)
    assert node.sql() == "orders.amount > refunds.amount"


def test_not_wraps_the_predicate() -> None:
    """NOT becomes an exp.Not around the operand."""
    node = _condition("NOT orders.status = 'paid'")

    assert isinstance(node, exp.Not)
    assert node.sql() == "NOT orders.status = 'paid'"


def test_not_keeps_the_grouping_of_an_or() -> None:
    """NOT over OR is parenthesized so the group stays together."""
    node = _condition("NOT (orders.status = 'paid' OR orders.status = 'shipped')")

    assert isinstance(node, exp.Not)
    assert node.sql() == ("NOT (orders.status = 'paid' OR orders.status = 'shipped')")


def test_in_list_builds_an_in_node() -> None:
    """IN lists keep every literal."""
    node = _condition("orders.status IN ('paid', 'shipped')")

    assert isinstance(node, exp.In)
    assert len(node.expressions) == 2
    assert node.sql() == "orders.status IN ('paid', 'shipped')"


def test_not_in_is_negated_with_not() -> None:
    """sqlglot's In has no negated flag, so exp.Not wraps it."""
    node = _condition("orders.status NOT IN ('test')")

    assert isinstance(node, exp.Not)
    assert isinstance(node.this, exp.In)
    assert node.sql() == "NOT orders.status IN ('test')"


def test_between_builds_a_between_node() -> None:
    """BETWEEN keeps both bounds."""
    node = _condition("orders.amount BETWEEN 100 AND 500")

    assert isinstance(node, exp.Between)
    assert node.sql() == "orders.amount BETWEEN 100 AND 500"


def test_not_between_is_negated_with_not() -> None:
    """NOT BETWEEN wraps the Between node."""
    node = _condition("orders.amount NOT BETWEEN 1 AND 2")

    assert isinstance(node, exp.Not)
    assert isinstance(node.this, exp.Between)


def test_is_null_builds_an_is_node() -> None:
    """IS NULL compares the column with a NULL literal."""
    node = _condition("orders.status IS NULL")

    assert isinstance(node, exp.Is)
    assert isinstance(node.expression, exp.Null)
    assert node.sql() == "orders.status IS NULL"


def test_is_not_null_is_negated_with_not() -> None:
    """IS NOT NULL wraps the Is node."""
    node = _condition("orders.status IS NOT NULL")

    assert isinstance(node, exp.Not)
    assert isinstance(node.this, exp.Is)


def test_like_builds_a_like_node() -> None:
    """LIKE keeps the pattern."""
    node = _condition("orders.status LIKE 'p%'")

    assert isinstance(node, exp.Like)
    assert node.sql() == "orders.status LIKE 'p%'"


def test_not_like_is_negated_with_not() -> None:
    """NOT LIKE wraps the Like node."""
    node = _condition("orders.status NOT LIKE 'p%'")

    assert isinstance(node, exp.Not)
    assert isinstance(node.this, exp.Like)


def test_in_list_binds_every_literal() -> None:
    """With bind_literals every IN value becomes a parameter."""
    context = _context(bind_literals=True)
    node = build_condition(
        parse_filter("orders.status IN ('paid', 'shipped')"), context
    )

    assert isinstance(node, exp.In)
    assert [str(item.this) for item in node.expressions] == ["param0", "param1"]
    assert dict(context.parameters) == {"param0": "paid", "param1": "shipped"}


def test_complex_filter_compiles_into_the_where_clause() -> None:
    """Nested filters reach the compiled WHERE clause intact."""
    model = _model()
    query = (
        model.q.group_by("orders.status")
        .calculate("revenue")
        .filter(
            "(orders.status = 'paid' OR orders.status = 'shipped') "
            "AND orders.amount BETWEEN 100 AND 500 "
            "AND orders.status NOT LIKE 'test%' "
            "AND orders.id IS NOT NULL"
        )
    )

    sql = _squash(query.compile(pretty=False)[0])

    assert "(orders.status = 'paid' OR orders.status = 'shipped')" in sql
    assert "orders.amount BETWEEN 100 AND 500" in sql
    assert "NOT orders.status LIKE 'test%'" in sql
    # sqlglot renders the canonical not-is-null AST as "NOT x IS NULL".
    assert "NOT orders.id IS NULL" in sql


def test_field_comparison_across_fact_entities_is_rejected() -> None:
    """A comparison of two facts cannot be pushed into one CTE."""
    model = _model()
    query = (
        model.q.group_by("orders.status")
        .calculate("revenue")
        .calculate("refund_total")
        .filter("refunds.amount > campaigns.budget")
    )

    with pytest.raises(ValueError, match="field-to-field comparison across fact"):
        query.compile()
