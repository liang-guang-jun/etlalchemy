"""Tests for the static fanout detection of the compile layer."""

from __future__ import annotations

import pytest
from etlalchemy.compile.compiler import compile_query
from etlalchemy.compile.context import CompileContext
from etlalchemy.compile.plan import FanoutRisk, detect_fanout
from etlalchemy.compile.resolve import resolve_query
from etlalchemy.compile.routes import select_edges
from etlalchemy.semantic import (
    Cardinality,
    FieldRef,
    Measure,
    Query,
    SemanticModel,
    SemanticRegistry,
    expression_join,
)
from etlalchemy.semantic.measure import SUPPORTED_AGGREGATIONS

from builders import entity, relationship


def _squash(sql: str) -> str:
    """Collapse whitespace so assertions survive pretty formatting."""
    return " ".join(sql.split())


def _measure(name: str, entity_alias: str, aggregation: str = "sum") -> Measure:
    """Build a measure over the primary key of one entity."""
    return Measure(
        name=name,
        field=FieldRef(entity=entity_alias, name="id"),
        aggregation=aggregation,
    )


def _model(
    *,
    cardinality: Cardinality = Cardinality.ONE_TO_MANY,
    aggregation: str = "sum",
) -> SemanticModel:
    """Build a one-edge model from a one end to a many end.

    ``teams`` is the source (one) end and ``members`` the target (many) end, so
    a measure on ``teams`` is fanned out by ``teams_members`` while a measure on
    ``members`` is not.
    """
    teams = entity("teams")
    members = entity("members")
    registry = SemanticRegistry(
        entities={"teams": teams, "members": members},
        relationships=[
            relationship("teams_members", teams, members, cardinality=cardinality)
        ],
    )
    registry.measures["team_total"] = _measure("team_total", "teams", aggregation)
    registry.measures["member_total"] = _measure("member_total", "members")
    return SemanticModel(name="fanout", registry=registry)


def _risks(model: SemanticModel, query: Query) -> tuple[FanoutRisk, ...]:
    """Run the static fanout detection for one query."""
    context = CompileContext(model=model, query=query)
    resolved = resolve_query(query, context)
    return detect_fanout(resolved, select_edges(resolved, context), model.registry)


def test_measure_aggregation_defaults_to_sum() -> None:
    """A measure without an aggregation stays a SUM measure."""
    measure = Measure(name="total", field=FieldRef(entity="orders", name="id"))

    assert measure.aggregation == "sum"


def test_measure_rejects_an_unsupported_aggregation() -> None:
    """Aggregations are validated when the measure is built."""
    with pytest.raises(ValueError, match="Unsupported aggregation"):
        Measure(
            name="median",
            field=FieldRef(entity="orders", name="id"),
            aggregation="median",
        )


def test_count_distinct_is_a_supported_aggregation() -> None:
    """count_distinct is part of the supported aggregation set."""
    measure = _measure("distinct_orders", "orders", "count_distinct")

    assert measure.aggregation == "count_distinct"
    assert "count_distinct" in SUPPORTED_AGGREGATIONS


def test_reverse_one_to_many_is_an_error_for_sum() -> None:
    """A measure on the one end of a ONE_TO_MANY edge cannot be summed."""
    model = _model()
    query = model.q.group_by("members.id").calculate("team_total")

    assert _risks(model, query) == (
        FanoutRisk(
            measure="team_total",
            entity_alias="teams",
            relationship="teams_members",
            reason="one_to_many_reverse",
            severity="error",
        ),
    )


def test_reverse_one_to_many_only_warns_for_min() -> None:
    """MIN is stable under duplicated rows, so the same risk only warns."""
    model = _model(aggregation="min")
    query = model.q.group_by("members.id").calculate("team_total")

    risks = _risks(model, query)

    assert [risk.reason for risk in risks] == ["one_to_many_reverse"]
    assert [risk.severity for risk in risks] == ["warning"]


def test_many_to_many_is_an_error_for_count_distinct() -> None:
    """MANY_TO_MANY always rejects, whatever the aggregation."""
    orders = entity("orders")
    patterns = entity("patterns")
    registry = SemanticRegistry(
        entities={"orders": orders, "patterns": patterns},
        relationships=[
            expression_join(
                name="orders_patterns",
                source_entity="orders",
                target_entity="patterns",
                expression="regexp_like({source}.id, {target}.id)",
                cardinality=Cardinality.MANY_TO_MANY,
            )
        ],
    )
    registry.measures["distinct_orders"] = _measure(
        "distinct_orders", "orders", "count_distinct"
    )
    model = SemanticModel(name="patterns", registry=registry)
    query = model.q.group_by("patterns.id").calculate("distinct_orders")

    risks = _risks(model, query)

    assert [(risk.reason, risk.severity) for risk in risks] == [
        ("many_to_many", "error")
    ]


def test_forward_one_to_many_is_not_a_risk() -> None:
    """A measure on the many end of a ONE_TO_MANY edge is not fanned out."""
    model = _model()
    query = model.q.group_by("teams.id").calculate("member_total")

    assert _risks(model, query) == ()


def test_count_distinct_compiles_into_a_distinct_count() -> None:
    """count_distinct renders COUNT(DISTINCT column)."""
    teams = entity("teams")
    members = entity("members")
    registry = SemanticRegistry(
        entities={"teams": teams, "members": members},
        relationships=[relationship("teams_members", teams, members)],
    )
    registry.measures["member_count"] = _measure(
        "member_count", "members", "count_distinct"
    )
    model = SemanticModel(name="distinct", registry=registry)
    query = model.q.group_by("teams.id").calculate("member_count")

    sql, _ = query.compile()

    assert "COUNT(DISTINCT members.id) AS member_count" in _squash(sql)


def test_compile_rejects_a_summed_measure_that_fans_out() -> None:
    """A fanout error stops the compilation and names measure and edge."""
    model = _model()
    query = model.q.group_by("members.id").calculate("team_total")

    with pytest.raises(ValueError) as excinfo:
        query.compile()

    message = str(excinfo.value)
    assert "Fanout detected for measure 'team_total'" in message
    assert "relationship 'teams_members'" in message
    assert "one_to_many_reverse" in message
    assert "Pre-aggregate the measure or change the aggregation." in message


def test_compile_reports_warning_level_fanout_risks() -> None:
    """include_report returns the report carrying the warning risks."""
    model = _model(aggregation="min")
    query = model.q.group_by("members.id").calculate("team_total")

    sql, params, report = query.compile(include_report=True)

    assert "MIN(teams.id) AS team_total" in _squash(sql)
    assert params == []
    assert [risk.measure for risk in report.fanout_risks] == ["team_total"]
    assert report.fanout_risks[0].severity == "warning"
    # teams holds the measure, so it is the base and the one end joins with LEFT.
    assert report.join_types == (("teams_members", "LEFT"),)


def test_compile_still_returns_two_values_by_default() -> None:
    """Without include_report the caller keeps the (sql, params) pair."""
    model = _model()
    query = model.q.group_by("teams.id").calculate("member_total")

    result = query.compile()

    assert len(result) == 2


def test_compile_query_returns_the_report_on_request() -> None:
    """The module entry point honours include_report as well."""
    model = _model()
    query = model.q.group_by("teams.id").calculate("member_total")

    sql, params, report = compile_query(query, model, include_report=True)

    assert query.compile()[0] == sql
    assert params == []
    assert report.fanout_risks == ()
