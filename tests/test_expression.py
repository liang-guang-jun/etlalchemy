"""Tests for the module-level query starters and Query chaining."""

from __future__ import annotations

import pytest
from etlalchemy.semantic import (
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


def test_order_by_takes_a_descending_flag() -> None:
    """Descending is an explicit argument, not part of the reference."""
    query = q.order_by("total_revenue", descending=True)

    assert query.order_terms == (OrderBy(ref="total_revenue", descending=True),)
    assert query.order_terms[0].descending is True


def test_order_by_defaults_to_ascending() -> None:
    """The default ordering is ascending."""
    query = q.order_by("total_revenue")

    assert query.order_terms == (OrderBy(ref="total_revenue", descending=False),)
    assert query.order_terms[0].descending is False


def test_order_by_starter_matches_the_instance_method() -> None:
    """The q starter and the instance method build the same ordering."""
    assert q.order_by("total_revenue", descending=True) == Query().order_by(
        "total_revenue", descending=True
    )


def test_model_starters_forward_the_descending_flag() -> None:
    """model.q.order_by carries both the flag and the model binding."""
    model = SemanticModel(name="crm")

    query = model.q.order_by("total_revenue", descending=True)

    assert query.model is model
    assert query.order_terms == (OrderBy(ref="total_revenue", descending=True),)


def test_order_by_appends_terms() -> None:
    """Repeated calls append ordering terms instead of replacing them."""
    query = q.order_by("total_revenue", descending=True).order_by("status")

    assert query.order_terms == (
        OrderBy(ref="total_revenue", descending=True),
        OrderBy(ref="status", descending=False),
    )


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


def test_group_by_accepts_an_output_alias() -> None:
    """A single dimension can be projected under a custom alias."""
    query = q.group_by("orders.status", alias="order_status")

    assert query.dimensions == (
        FieldRef(entity="orders", name="status", alias="order_status"),
    )
    assert query.dimensions[0].alias == "order_status"


def test_group_by_without_alias_leaves_it_unset() -> None:
    """Dimensions start without an alias and get the default at compile time."""
    assert q.group_by("orders.status").dimensions[0].alias is None


def test_group_by_rejects_alias_for_several_refs() -> None:
    """An alias cannot name more than one dimension."""
    with pytest.raises(ValueError, match="alias is only valid with a single"):
        q.group_by("orders.status", "users.region", alias="x")


def test_module_level_group_by_keeps_the_alias_and_model_binding() -> None:
    """The module-level starter forwards the alias and stays unbound."""
    unbound = q.group_by("orders.status", alias="order_status")
    bound = SemanticModel(name="crm").q.group_by("orders.status", alias="order_status")

    assert unbound.model is None
    assert unbound.dimensions[0].alias == "order_status"
    assert bound.model is not None
    assert bound.dimensions[0].alias == "order_status"


def test_field_ref_equality_includes_the_alias() -> None:
    """Field references with different aliases are not equal."""
    assert FieldRef(entity="a", name="b") != FieldRef(entity="a", name="b", alias="x")
    assert FieldRef(entity="a", name="b") == FieldRef(entity="a", name="b")


def test_invalid_inputs_raise_value_error() -> None:
    """Malformed references, predicates and ordering terms are rejected."""
    with pytest.raises(ValueError, match="alias.field"):
        q.group_by("status")

    with pytest.raises(ValueError, match="use alias.field"):
        q.filter("status = 'paid'")

    with pytest.raises(ValueError, match="Invalid filter at position"):
        q.filter("orders.status = ")


def test_filter_accepts_like_and_mixed_logical_operators() -> None:
    """The DSL nests operators, so LIKE and mixed AND/OR are valid now."""
    predicate = q.filter(
        "orders.status LIKE 'p%' OR orders.status = 'paid' AND orders.total > 1"
    ).filters[0]

    assert isinstance(predicate, Logical)
    assert predicate.operator == "OR"


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
    with pytest.raises(ValueError, match="build it with model.q"):
        q.limit(10).compile()


def test_compile_passes_the_bound_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """query.compile forwards itself, its model, the dialect and the flags."""
    model = SemanticModel(name="crm")
    calls: list[tuple[Query, SemanticModel, str, bool, bool]] = []

    def fake_compile(
        query: Query,
        bound_model: SemanticModel,
        dialect: str = "postgres",
        *,
        bind_literals: bool = False,
        pretty: bool = True,
        unreachable_dimensions: str = "error",
        nulls_first: bool | None = None,
        include_report: bool = False,
    ) -> tuple[str, list[object]]:
        calls.append((query, bound_model, dialect, bind_literals, pretty))
        return "SELECT 1", []

    monkeypatch.setattr("etlalchemy.compile.compiler.compile_query", fake_compile)
    query = model.q.group_by("orders.status")

    sql, parameters = query.compile(dialect="duckdb", bind_literals=True, pretty=False)

    assert (sql, parameters) == ("SELECT 1", [])
    assert calls == [(query, model, "duckdb", True, False)]


def test_query_equality_ignores_the_model() -> None:
    """Same content on different models still compares equal."""
    first = SemanticModel(name="a").q.group_by("orders.status")
    second = SemanticModel(name="b").q.group_by("orders.status")

    assert first.model is not second.model
    assert first == second
