"""Tests for the module-level query starters and Query chaining."""

from __future__ import annotations

import pytest
from etlalchemy.core import (
    Comparison,
    FieldRef,
    Literal,
    Logical,
    MeasureRef,
    OrderBy,
    Query,
    SemanticModel,
    q,
)


def test_starter_chain_builds_dimensions_measures_and_limit() -> None:
    """q.group_by(...).calculate(...).limit(...) builds the expected query."""
    query = q.group_by("orders.status").calculate("revenue").limit(10)

    assert isinstance(query, Query)
    assert query.dimensions == (FieldRef(entity="orders", name="status"),)
    assert query.measures == (MeasureRef(name="revenue"),)
    assert query.row_limit == 10


def test_calculate_keeps_an_output_alias() -> None:
    """calculate accepts an alias for the projected measure."""
    query = q.calculate("revenue", alias="total_revenue")

    assert query.measures == (MeasureRef(name="revenue", alias="total_revenue"),)


def test_filter_parses_a_comparison() -> None:
    """A single predicate string becomes a structured Comparison."""
    query = q.filter("orders.status = 'paid'")

    assert len(query.filters) == 1
    predicate = query.filters[0]
    assert isinstance(predicate, Comparison)
    assert predicate.field == FieldRef(entity="orders", name="status")
    assert predicate.operator == "="
    assert predicate.value == Literal("paid")


def test_filter_parses_numeric_and_boolean_literals() -> None:
    """Literals are typed when the text allows it."""
    query = q.filter("orders.total >= 100")

    predicate = query.filters[0]
    assert isinstance(predicate, Comparison)
    assert predicate.value == Literal(100)


def test_filter_combines_predicates_with_and() -> None:
    """An AND predicate becomes a Logical node with both operands."""
    predicate = q.filter("orders.status = 'paid' AND orders.total > 100").filters[0]

    assert isinstance(predicate, Logical)
    assert predicate.operator == "AND"
    assert len(predicate.operands) == 2


def test_order_by_parses_descending() -> None:
    """The trailing direction keyword sets descending."""
    query = q.order_by("total_revenue DESC")

    assert query.order_terms == (OrderBy(ref="total_revenue", descending=True),)


def test_order_by_defaults_to_ascending() -> None:
    """A term without a direction keeps the default ordering."""
    query = q.order_by("total_revenue")

    assert query.order_terms == (OrderBy(ref="total_revenue", descending=False),)


def test_route_records_an_alias_pair() -> None:
    """Routes are keyed by entity aliases, not entity ids."""
    query = q.route("orders", "users", 0)

    assert query.routes == {("orders", "users"): 0}


def test_limit_accepts_zero_and_rejects_negative() -> None:
    """Limits must be non-negative."""
    assert q.limit(10).row_limit == 10
    assert q.limit(0).row_limit == 0

    with pytest.raises(ValueError, match="non-negative"):
        q.limit(-1)


def test_instance_methods_append_without_mutating() -> None:
    """Chaining returns a new query and leaves the original untouched."""
    base = q.group_by("orders.status")
    extended = base.group_by("users.region")

    assert extended.dimensions == (
        FieldRef(entity="orders", name="status"),
        FieldRef(entity="users", name="region"),
    )
    assert base.dimensions == (FieldRef(entity="orders", name="status"),)


def test_invalid_inputs_raise_value_error() -> None:
    """Malformed references, predicates and ordering terms are rejected."""
    with pytest.raises(ValueError, match="alias.field"):
        q.group_by("status")

    with pytest.raises(ValueError, match="Unsupported predicate"):
        q.filter("orders.status LIKE 'paid'")

    with pytest.raises(ValueError, match="Mixed logical operators"):
        q.filter("orders.status = 'paid' AND orders.total > 1 OR orders.id = 2")


def test_module_level_starters_build_unbound_queries() -> None:
    """The module-level q never binds a model."""
    assert q.group_by("orders.status").model is None
    assert q.limit(1).model is None


def test_model_starters_bind_the_model() -> None:
    """Queries started from model.q carry that model."""
    model = SemanticModel(name="crm")

    query = model.q.group_by("orders.status").calculate("revenue")

    assert query.model is model
    assert query.dimensions == (FieldRef(entity="orders", name="status"),)
    assert query.measures == (MeasureRef(name="revenue"),)


def test_compile_requires_a_bound_model() -> None:
    """Compiling an unbound query fails with a helpful message."""
    with pytest.raises(ValueError, match="not bound to a model"):
        q.limit(10).compile()


def test_compile_passes_the_bound_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """query.compile forwards itself, its model and the dialect."""
    model = SemanticModel(name="crm")
    calls: list[tuple[Query, SemanticModel, str]] = []

    def fake_compile(
        query: Query, bound_model: SemanticModel, dialect: str = "postgres"
    ) -> tuple[str, list[object]]:
        calls.append((query, bound_model, dialect))
        return "SELECT 1", []

    monkeypatch.setattr("etlalchemy.compile.compiler.compile_query", fake_compile)
    query = model.q.group_by("orders.status")

    sql, parameters = query.compile(dialect="duckdb")

    assert (sql, parameters) == ("SELECT 1", [])
    assert calls == [(query, model, "duckdb")]


def test_query_equality_ignores_the_model() -> None:
    """Same content on different models still compares equal."""
    first = SemanticModel(name="a").q.group_by("orders.status")
    second = SemanticModel(name="b").q.group_by("orders.status")

    assert first.model is not second.model
    assert first == second
