"""Tests for multi-column measures and aggregate building."""

from __future__ import annotations

import dataclasses
from uuid import UUID, uuid5

import pytest
from etlalchemy.compile.aggregate import build_aggregation
from etlalchemy.compile.context import CompileContext
from etlalchemy.compile.resolve import resolve_query
from etlalchemy.semantic import (
    Field,
    FieldRef,
    Materialization,
    Measure,
    Rowset,
    SemanticEntity,
    SemanticModel,
    SemanticRegistry,
    String,
)
from sqlglot import exp

from builders import entity, relationship

NAMESPACE = UUID("00000000-0000-0000-0000-000000000000")

#: Aggregations that reject a ``fields`` tuple.
SIMPLE_AGGREGATIONS = ("sum", "count", "avg", "min", "max")

#: Aggregations that require their single field.
FIELD_REQUIRED_AGGREGATIONS = ("sum", "avg", "min", "max")


def _squash(sql: str) -> str:
    """Collapse whitespace so assertions survive pretty formatting."""
    return " ".join(sql.split())


def _orders() -> SemanticEntity:
    """Build an order entity with the columns the measures need."""
    rowset = Rowset(
        name="crm.orders",
        kind=Materialization.TABLE,
        fields={
            name: Field(name=name, data_type=String())
            for name in ("id", "user_id", "order_id", "amount")
        },
        primary_key=["id"],
    )
    return SemanticEntity(
        id=uuid5(NAMESPACE, "orders"), alias="orders", relation=rowset
    )


def _model() -> SemanticModel:
    """Build a model with a multi-column distinct measure and simple ones."""
    orders = _orders()
    registry = SemanticRegistry(entities={"orders": orders})
    registry.measures["unique_user_product"] = Measure(
        name="unique_user_product",
        fields=(FieldRef("orders", "user_id"), FieldRef("orders", "order_id")),
        aggregation="count_distinct",
    )
    registry.measures["distinct_users"] = Measure(
        name="distinct_users",
        field=FieldRef("orders", "user_id"),
        aggregation="count_distinct",
    )
    registry.measures["revenue"] = Measure(
        name="revenue", field=FieldRef("orders", "amount")
    )
    return SemanticModel(name="crm", registry=registry)


def _aggregate(model: SemanticModel, measure_name: str) -> exp.Expression:
    """Resolve one measure and return its built aggregate expression."""
    query = model.q.calculate(measure_name)
    context = CompileContext(model=model, query=query)
    resolved = resolve_query(query, context)
    return build_aggregation(resolved.measures[0], context)


def test_measure_field_defaults_are_unset() -> None:
    """A Measure declares no field and no fields unless they are given."""
    defaults = {
        item.name: item.default
        for item in dataclasses.fields(Measure)
        if item.name in {"field", "fields", "entity"}
    }

    assert defaults == {"field": None, "fields": (), "entity": None}


def test_count_distinct_rejects_field_and_fields_together() -> None:
    """count_distinct takes one column or a tuple, never both."""
    with pytest.raises(ValueError, match="either field or fields, not both"):
        Measure(
            name="both",
            field=FieldRef("orders", "id"),
            fields=(FieldRef("orders", "user_id"),),
            aggregation="count_distinct",
        )


def test_count_distinct_requires_a_field_or_fields() -> None:
    """A distinct measure without any column is rejected."""
    with pytest.raises(ValueError, match="requires a field or fields"):
        Measure(name="empty", aggregation="count_distinct")


@pytest.mark.parametrize("aggregation", SIMPLE_AGGREGATIONS)
def test_other_aggregations_reject_fields(aggregation: str) -> None:
    """Only count_distinct accepts several columns."""
    with pytest.raises(ValueError, match="does not accept fields"):
        Measure(
            name="multi",
            field=FieldRef("orders", "id"),
            fields=(FieldRef("orders", "user_id"),),
            aggregation=aggregation,
        )


@pytest.mark.parametrize("aggregation", FIELD_REQUIRED_AGGREGATIONS)
def test_field_aggregations_require_a_field(aggregation: str) -> None:
    """sum, avg, min and max still need their single field."""
    with pytest.raises(ValueError, match="requires a field"):
        Measure(name="missing", aggregation=aggregation)


def test_count_rejects_fields_and_points_at_the_two_forms() -> None:
    """count takes field or nothing, never a fields tuple."""
    with pytest.raises(ValueError, match="pass field for COUNT"):
        Measure(
            name="rows",
            fields=(FieldRef("orders", "user_id"),),
            aggregation="count",
        )


def test_count_without_columns_is_allowed_at_construction() -> None:
    """COUNT(*) has no field, so construction accepts an empty measure."""
    measure = Measure(name="rows", aggregation="count")

    assert measure.field is None
    assert measure.fields == ()
    assert measure.entity is None


def test_count_star_requires_an_entity_hint_when_resolving() -> None:
    """A COUNT(*) measure needs entity because no field names the fact."""
    model = _model()
    model.registry.measures["rows"] = Measure(name="rows", aggregation="count")

    with pytest.raises(ValueError, match="COUNT\\(\\*\\) measures must set entity"):
        model.q.calculate("rows").compile()


def test_count_star_resolves_through_the_entity_hint() -> None:
    """The entity hint supplies the fact entity of a COUNT(*) measure."""
    model = _model()
    model.registry.measures["rows"] = Measure(
        name="rows", entity="orders", aggregation="count"
    )
    query = model.q.calculate("rows")
    context = CompileContext(model=model, query=query)

    resolved = resolve_query(query, context).measures[0]

    assert resolved.entity.alias == "orders"
    assert resolved.field is None
    assert resolved.fields == ()


def test_count_star_builds_a_star_aggregate() -> None:
    """COUNT(*) wraps exp.Star instead of a column."""
    model = _model()
    model.registry.measures["rows"] = Measure(
        name="rows", entity="orders", aggregation="count"
    )

    node = _aggregate(model, "rows")

    assert isinstance(node, exp.Count)
    assert isinstance(node.this, exp.Star)
    assert node.sql() == "COUNT(*)"


def test_count_with_a_field_still_counts_that_column() -> None:
    """COUNT(field) keeps its column and is unaffected by COUNT(*)."""
    model = _model()
    model.registry.measures["order_count"] = Measure(
        name="order_count", field=FieldRef("orders", "order_id"), aggregation="count"
    )

    node = _aggregate(model, "order_count")

    assert node.sql() == "COUNT(orders.order_id)"


def test_count_star_is_rejected_across_fact_entities() -> None:
    """COUNT(*) cannot be merged from several fact CTEs yet."""
    orders = _orders()
    refunds = entity("refunds")
    registry = SemanticRegistry(
        entities={"orders": orders, "refunds": refunds},
        relationships=[relationship("orders_refunds", orders, refunds)],
    )
    registry.measures["rows"] = Measure(
        name="rows", entity="orders", aggregation="count"
    )
    registry.measures["refund_total"] = Measure(
        name="refund_total", field=FieldRef("refunds", "id")
    )
    model = SemanticModel(name="crm", registry=registry)
    query = model.q.group_by("orders.id").calculate("rows").calculate("refund_total")

    with pytest.raises(ValueError, match="count across multiple fact"):
        query.compile()


def test_single_column_count_distinct_wraps_one_expression() -> None:
    """The single-column form renders COUNT(DISTINCT col)."""
    node = _aggregate(_model(), "distinct_users")

    assert isinstance(node, exp.Count)
    distinct = node.this
    assert isinstance(distinct, exp.Distinct)
    assert [column.sql() for column in distinct.expressions] == ["orders.user_id"]


def test_multi_column_count_distinct_wraps_each_field() -> None:
    """The fields form keeps one column per declared field, in order."""
    node = _aggregate(_model(), "unique_user_product")

    assert isinstance(node, exp.Count)
    distinct = node.this
    assert isinstance(distinct, exp.Distinct)
    assert [column.sql() for column in distinct.expressions] == [
        "orders.user_id",
        "orders.order_id",
    ]


def test_simple_aggregations_still_wrap_the_single_field() -> None:
    """SUM keeps its single-column shape after the refactor."""
    node = _aggregate(_model(), "revenue")

    assert isinstance(node, exp.Sum)
    assert node.sql() == "SUM(orders.amount)"


def test_multi_column_count_distinct_renders_natively_on_databricks() -> None:
    """Databricks keeps the columns in one COUNT(DISTINCT ...)."""
    model = _model()
    query = model.q.calculate("unique_user_product")

    sql = query.compile(dialect="databricks").sql

    assert "COUNT(DISTINCT orders.user_id, orders.order_id)" in _squash(sql)


def test_count_distinct_fields_must_share_the_measure_entity() -> None:
    """Fields of another entity are rejected while resolving the measure."""
    orders = _orders()
    users = entity("users")
    registry = SemanticRegistry(
        entities={"orders": orders, "users": users},
        relationships=[relationship("orders_users", orders, users)],
    )
    registry.measures["mixed"] = Measure(
        name="mixed",
        fields=(FieldRef("orders", "user_id"), FieldRef("users", "id")),
        aggregation="count_distinct",
    )
    model = SemanticModel(name="crm", registry=registry)

    with pytest.raises(ValueError, match="must belong to the same entity"):
        model.q.calculate("mixed").compile()


def test_count_distinct_is_rejected_across_fact_entities() -> None:
    """DISTINCT cannot be merged from several fact CTEs yet."""
    orders = _orders()
    refunds = entity("refunds")
    registry = SemanticRegistry(
        entities={"orders": orders, "refunds": refunds},
        relationships=[relationship("orders_refunds", orders, refunds)],
    )
    registry.measures["unique_user_product"] = Measure(
        name="unique_user_product",
        fields=(FieldRef("orders", "user_id"), FieldRef("orders", "order_id")),
        aggregation="count_distinct",
    )
    registry.measures["refund_total"] = Measure(
        name="refund_total", field=FieldRef("refunds", "id")
    )
    model = SemanticModel(name="crm", registry=registry)
    query = (
        model.q.group_by("orders.id")
        .calculate("unique_user_product")
        .calculate("refund_total")
    )

    with pytest.raises(ValueError, match="count_distinct across multiple fact"):
        query.compile()
