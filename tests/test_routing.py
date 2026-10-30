"""Tests for measure routes, query routes and their merge order."""

from __future__ import annotations

from etlalchemy.semantic import (
    FieldRef,
    Measure,
    Query,
    SemanticRegistry,
    effective_routes,
)

PAIR: tuple[str, str] = ("employees", "departments")
OTHER_PAIR: tuple[str, str] = ("assignments", "projects")


def _measure(
    name: str = "total", routes: dict[tuple[str, str], int] | None = None
) -> Measure:
    """Build a measure over one field with the given default routes."""
    return Measure(
        name=name,
        field=FieldRef(entity="orders", name="amount"),
        routes=routes or {},
    )


def test_measure_routes_override_query_routes() -> None:
    """A measure-level route wins over the query default for the same pair."""
    measure = _measure(routes={PAIR: 0})
    query = Query(routes={PAIR: 1})

    assert effective_routes(measure, query)[PAIR] == 0


def test_measure_routes_apply_when_the_query_is_empty() -> None:
    """The measure default is used for pairs the query does not name."""
    measure = _measure(routes={PAIR: 0})

    assert effective_routes(measure, Query())[PAIR] == 0


def test_no_routes_yields_an_empty_mapping() -> None:
    """An empty result means every pair falls back to the highest priority."""
    assert effective_routes(_measure(), Query()) == {}


def test_measures_in_one_query_keep_independent_routes() -> None:
    """Two measures with different defaults do not affect each other."""
    measure_a = _measure("a", {PAIR: 0})
    measure_b = _measure("b", {PAIR: 1})
    query = Query()

    assert effective_routes(measure_a, query) == {PAIR: 0}
    assert effective_routes(measure_b, query) == {PAIR: 1}


def test_merge_keeps_measure_and_query_pairs_side_by_side() -> None:
    """Pairs only the measure names survive next to pairs only the query names."""
    measure = _measure(routes={PAIR: 0})
    query = Query(routes={OTHER_PAIR: 2})

    assert effective_routes(measure, query) == {PAIR: 0, OTHER_PAIR: 2}


def test_merge_does_not_mutate_its_inputs() -> None:
    """The merge returns a new mapping and leaves both nodes untouched."""
    measure_routes = {PAIR: 0}
    query_routes = {OTHER_PAIR: 2}
    measure = _measure(routes=measure_routes)
    query = Query(routes=query_routes)

    merged = effective_routes(measure, query)
    assert merged is not measure.routes
    dict(merged)[PAIR] = 9

    assert measure.routes == {PAIR: 0}
    assert query.routes == {OTHER_PAIR: 2}


def test_query_defaults_to_no_routes() -> None:
    """An unconfigured query and measure both use the highest priority."""
    assert Query().routes == {}
    assert _measure().routes == {}


def test_registry_registers_measures_by_name() -> None:
    """Measures are stored in the registry keyed by their name."""
    registry = SemanticRegistry()
    revenue = _measure("revenue")
    cost = _measure("cost")
    registry.measures[revenue.name] = revenue
    registry.measures[cost.name] = cost

    assert registry.measures["revenue"] is revenue
    assert registry.measures["cost"] is cost
    assert sorted(registry.measures) == ["cost", "revenue"]
