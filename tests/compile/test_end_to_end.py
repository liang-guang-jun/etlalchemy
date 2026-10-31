"""End-to-end tests for the semantic query compiler."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from uuid import UUID, uuid5

import pytest
import sqlglot
from etlalchemy.compile import CompiledQuery, compile_query
from etlalchemy.compile.context import CompileContext
from etlalchemy.compile.plan import (
    choose_base_entity,
    choose_join_type,
    group_measures_by_entity,
    plan_ctes,
    plan_join_paths,
    plan_joins,
    referenced_entities,
)
from etlalchemy.compile.resolve import ResolvedQuery, resolve_query
from etlalchemy.compile.routes import select_edges
from etlalchemy.semantic import (
    Cardinality,
    Comparison,
    Field,
    FieldCollection,
    FieldRef,
    FilterDirection,
    Literal,
    Materialization,
    Measure,
    Query,
    RelationshipCycleError,
    Rowset,
    SemanticEntity,
    SemanticModel,
    SemanticRegistry,
    SemanticRelationship,
    String,
    equi_join,
)
from sqlglot import exp

NAMESPACE = UUID("00000000-0000-0000-0000-000000000000")


def _entity(alias: str, *fields: str) -> SemanticEntity:
    """Build a string-only entity with a single primary key."""
    rowset = Rowset(
        name=f"crm.{alias}",
        kind=Materialization.TABLE,
        fields={name: Field(name=name, data_type=String()) for name in fields},
        primary_key=["id"],
    )
    return SemanticEntity(
        id=uuid5(NAMESPACE, alias),
        alias=alias,
        relation=rowset,
    )


def _resolved(
    model: SemanticModel, query: Query
) -> tuple[CompileContext, ResolvedQuery]:
    """Resolve a query against a model for planner-level tests."""
    context = CompileContext(model=model, query=query)
    return context, resolve_query(query, context)


def _relationship(
    name: str,
    source: SemanticEntity,
    source_field: str,
    target: SemanticEntity,
    target_field: str,
    priority: int = 0,
) -> SemanticRelationship:
    """Build a single-column relationship between two entities."""
    return equi_join(
        name=name,
        source=FieldCollection(source, (source.relation.fields[source_field],)),
        target=FieldCollection(target, (target.relation.fields[target_field],)),
        priority=priority,
    )


def _model(*, cyclic: bool = False) -> SemanticModel:
    """Build a small CRM model with two fact tables and an unused table."""
    orders = _entity("orders", "id", "status", "total", "customer_id", "region")
    customers = _entity("customers", "id", "region", "name")
    regions = _entity("regions", "id", "name")
    refunds = _entity("refunds", "id", "order_id", "amount", "reason")
    campaigns = _entity("campaigns", "id", "name")
    relationships = [
        # priority 1 is the default route for the (orders, customers) pair.
        _relationship("orders_customers_id", orders, "customer_id", customers, "id", 1),
        _relationship(
            "orders_customers_region", orders, "region", customers, "region", 0
        ),
        # Connected but never referenced by most queries below.
        _relationship("orders_regions", orders, "region", regions, "id", 0),
        # Second fact table sharing the customers dimension through orders.
        _relationship("refunds_orders", refunds, "order_id", orders, "id", 0),
    ]
    if cyclic:
        relationships.append(
            _relationship(
                "customers_orders_id", customers, "id", orders, "customer_id", 0
            )
        )
    registry = SemanticRegistry(
        entities={
            "orders": orders,
            "customers": customers,
            "regions": regions,
            "refunds": refunds,
            # Registered but disconnected: no CTE can aggregate by it.
            "campaigns": campaigns,
        },
        relationships=relationships,
    )
    registry.measures["revenue"] = Measure(
        name="revenue", field=FieldRef(entity="orders", name="total")
    )
    registry.measures["order_count"] = Measure(
        name="order_count",
        field=FieldRef(entity="orders", name="id"),
        aggregation="count",
    )
    registry.measures["customer_count"] = Measure(
        name="customer_count",
        field=FieldRef(entity="customers", name="id"),
        aggregation="count",
    )
    registry.measures["refund_total"] = Measure(
        name="refund_total", field=FieldRef(entity="refunds", name="amount")
    )
    # MIN only warns about a fanout join, which keeps the join and CTE tests
    # below focused on their own behaviour instead of on fanout detection.
    registry.measures["min_total"] = Measure(
        name="min_total",
        field=FieldRef(entity="orders", name="total"),
        aggregation="min",
    )
    registry.measures["min_refund"] = Measure(
        name="min_refund",
        field=FieldRef(entity="refunds", name="amount"),
        aggregation="min",
    )
    return SemanticModel(name="crm", registry=registry)


def test_compiles_a_dimension_and_measure_with_limit(
    squash: Callable[[str], str],
) -> None:
    """A single-entity query selects, groups, orders and limits."""
    model = _model()
    query = model.q.group_by("orders.status").calculate("revenue").limit(10)

    compiled = query.compile()

    statement = sqlglot.parse_one(compiled.sql, read="postgres")
    assert isinstance(statement, exp.Select)
    assert [item.alias for item in statement.expressions] == [
        "orders__status",
        "revenue",
    ]
    source = statement.find(exp.From)
    assert source is not None
    assert isinstance(source.this, exp.Table)
    assert source.this.name == "orders"
    assert not statement.args.get("joins")
    assert "SUM(orders.total) AS revenue" in squash(compiled.sql)
    assert "GROUP BY orders.status" in squash(compiled.sql)
    assert "LIMIT 10" in squash(compiled.sql)
    assert compiled.params == []


def test_dimension_alias_is_used_as_the_output_name(
    squash: Callable[[str], str],
) -> None:
    """A dimension alias becomes the projected column name and the ordering key."""
    model = _model()
    query = (
        model.q.group_by("orders.status", alias="order_status")
        .calculate("revenue")
        .order_by("order_status")
    )

    sql = query.compile().sql

    statement = sqlglot.parse_one(sql, read="postgres")
    assert [item.alias for item in statement.expressions] == [
        "order_status",
        "revenue",
    ]
    assert "ORDER BY order_status" in squash(sql)


def test_order_by_rejects_an_unknown_dimension_alias() -> None:
    """The default dimension alias is 'entity__name', not 'entity.name'."""
    model = _model()
    query = model.q.group_by("orders.status").order_by("orders.status")

    with pytest.raises(ValueError, match="Unknown ordering alias"):
        query.compile()


def test_compiles_without_group_by_when_there_are_no_dimensions(
    squash: Callable[[str], str],
) -> None:
    """A pure aggregate query has no GROUP BY clause."""
    model = _model()

    sql = model.q.calculate("revenue").compile().sql

    assert "GROUP BY" not in squash(sql)
    assert "SUM(orders.total) AS revenue" in squash(sql)


def test_compiles_a_left_join_when_the_base_is_on_the_many_side(
    squash: Callable[[str], str],
) -> None:
    """A ONE_TO_MANY edge joins with LEFT from either end."""
    model = _model()

    sql = model.q.group_by("orders.status").calculate("customer_count").compile().sql

    statement = sqlglot.parse_one(sql, read="postgres")
    joins = statement.args.get("joins")
    assert joins is not None
    assert len(joins) == 1
    # The edge is ONE_TO_MANY in the SINGLE direction, so it is LEFT even though
    # the base sits on the many end: unmatched orders keep NULL customers.
    assert "LEFT JOIN crm.orders AS orders" in squash(sql)
    assert "ON orders.customer_id = customers.id" in squash(sql)
    assert "COUNT(customers.id) AS customer_count" in squash(sql)


def test_compiles_a_left_join_from_the_base_to_the_many_side(
    squash: Callable[[str], str],
) -> None:
    """A fact-table base keeps all its rows when joining a dimension."""
    model = _model()

    # min_total only warns about the reverse one-to-many join, so the LEFT JOIN
    # shape is still the behaviour under test here.
    sql = model.q.group_by("customers.region").calculate("min_total").compile().sql

    assert "LEFT JOIN crm.customers AS customers" in squash(sql)
    assert "ON orders.customer_id = customers.id" in squash(sql)


def test_query_routes_pick_a_different_relationship(
    squash: Callable[[str], str],
) -> None:
    """An explicit route switches the join to the lower-priority edge."""
    model = _model()
    query = (
        model.q.group_by("orders.status")
        .calculate("customer_count")
        .route("orders", "customers", 0)
    )

    sql = query.compile().sql

    assert "ON orders.region = customers.region" in squash(sql)
    assert "customer_id" not in squash(sql)


def test_literals_are_inlined_by_default(
    squash: Callable[[str], str],
) -> None:
    """The default mode inlines literals and returns no parameters."""
    model = _model()
    query = (
        model.q.group_by("orders.status")
        .calculate("revenue")
        .filter("orders.status = 'paid'")
    )

    compiled = query.compile()

    assert "'paid'" in squash(compiled.sql)
    assert "%(param0)s" not in compiled.sql
    assert compiled.params == []


def test_inline_literals_false_returns_named_parameters() -> None:
    """Parameterised literals become placeholders with a name-to-value map."""
    model = _model()
    query = (
        model.q.group_by("orders.status")
        .calculate("revenue")
        .filter("orders.status = 'paid'")
    )

    compiled = query.compile(dialect="postgres", inline_literals=False)

    assert compiled.params == {"param0": "paid"}
    assert "%(param0)s" in compiled.sql
    assert "'paid'" not in compiled.sql

    duckdb = query.compile(dialect="duckdb", inline_literals=False)
    assert duckdb.params == {"param0": "paid"}
    assert "$param0" in duckdb.sql


def test_compiled_query_carries_its_compile_options() -> None:
    """Every option used to compile the statement is carried on the result."""
    model = _model()
    query = model.q.group_by("orders.status").calculate("revenue")

    compiled = query.compile()

    assert isinstance(compiled, CompiledQuery)
    assert compiled.dialect == "databricks"
    assert compiled.inline_literals is True
    assert compiled.nulls_first is None
    assert compiled.params == []
    assert compiled.report is not None
    assert compiled.sql


def test_default_dialect_is_databricks() -> None:
    """The default dialect renders the statement for Databricks."""
    model = _model()
    query = model.q.group_by("orders.status").calculate("revenue")

    compiled = query.compile()

    assert compiled.dialect == "databricks"
    assert compiled.sql == query.compile(dialect="databricks").sql


def test_default_null_placement_renders_no_nulls_clause() -> None:
    """The default nulls_first=None leaves NULL placement to the database."""
    model = _model()
    query = _ordered_query(model)

    compiled = query.compile()

    assert compiled.nulls_first is None
    assert "NULLS FIRST" not in compiled.sql
    assert "NULLS LAST" not in compiled.sql


def test_inline_literals_false_parameterizes_the_statement() -> None:
    """Parameterised compilation returns the bound values with the SQL."""
    model = _model()
    query = (
        model.q.group_by("orders.status")
        .calculate("revenue")
        .filter("orders.status = 'paid'")
    )

    compiled = query.compile(dialect="postgres", inline_literals=False)

    assert compiled.inline_literals is False
    assert "'paid'" not in compiled.sql
    assert compiled.params == {"param0": "paid"}


def test_logical_predicates_bind_both_literals(
    squash: Callable[[str], str],
) -> None:
    """An AND predicate binds every literal in order."""
    model = _model()
    query = (
        model.q.group_by("orders.status")
        .calculate("revenue")
        .filter("orders.status = 'paid' AND orders.total > 100")
    )

    compiled = query.compile(dialect="postgres", inline_literals=False)

    assert compiled.params == {"param0": "paid", "param1": 100}
    assert "%(param0)s" in compiled.sql
    assert "%(param1)s" in compiled.sql
    assert "AND" in squash(compiled.sql)


def test_pretty_controls_line_breaks() -> None:
    """Pretty output spans lines; compact output stays on one line."""
    model = _model()
    query = model.q.group_by("orders.status").calculate("revenue").limit(10)

    pretty_sql = query.compile(pretty=True).sql
    compact_sql = query.compile(pretty=False).sql

    assert "\n" in pretty_sql
    assert "\n" not in compact_sql


def test_order_by_uses_the_measure_alias(
    squash: Callable[[str], str],
) -> None:
    """Ordering by a measure alias renders the alias in ORDER BY."""
    model = _model()

    sql = (
        model.q.group_by("orders.status")
        .calculate("revenue")
        .order_by("revenue", descending=True)
        .compile()
        .sql
    )

    assert "ORDER BY revenue DESC" in squash(sql)


def _ordered_query(model: SemanticModel) -> Query:
    """Build a query with one ascending and one descending order term."""
    return (
        model.q.group_by("orders.status", alias="order_status")
        .calculate("revenue")
        .order_by("order_status")
        .order_by("revenue", descending=True)
    )


def test_no_nulls_clause_is_rendered_by_default() -> None:
    """With nulls_first=None no NULLS FIRST/LAST clause appears."""
    model = _model()
    query = _ordered_query(model)

    for dialect in ("postgres", "databricks"):
        sql = query.compile(dialect=dialect).sql
        assert "NULLS FIRST" not in sql
        assert "NULLS LAST" not in sql


def test_nulls_first_false_renders_nulls_last_for_both_directions(
    squash: Callable[[str], str],
) -> None:
    """nulls_first=False puts NULLS LAST on ASC and DESC terms alike."""
    model = _model()
    query = _ordered_query(model)

    sql = query.compile(nulls_first=False).sql
    normalized = squash(sql)

    assert "order_status NULLS LAST" in normalized
    assert "revenue DESC NULLS LAST" in normalized
    assert "NULLS FIRST" not in normalized

    # An explicit placement is identical on every dialect.
    databricks_sql = query.compile(dialect="databricks", nulls_first=False).sql
    assert (
        squash(databricks_sql).split("ORDER BY")[1] == normalized.split("ORDER BY")[1]
    )


def test_nulls_first_true_renders_nulls_first_for_both_directions(
    squash: Callable[[str], str],
) -> None:
    """nulls_first=True puts NULLS FIRST on ASC and DESC terms alike."""
    model = _model()
    query = _ordered_query(model)

    sql = query.compile(nulls_first=True).sql
    normalized = squash(sql)

    assert "order_status NULLS FIRST" in normalized
    assert "revenue DESC NULLS FIRST" in normalized
    assert "NULLS LAST" not in normalized


def test_default_null_placement_depends_on_the_dialect(
    squash: Callable[[str], str],
) -> None:
    """With nulls_first=None the database default decides where NULLs sort."""
    model = _model()
    query = _ordered_query(model)

    postgres_sql = query.compile(dialect="postgres").sql
    databricks_sql = query.compile(dialect="databricks").sql

    # No NULLS clause is rendered, so the dialects keep their own defaults:
    # ASC sorts NULLs last on Postgres but first on Databricks. That is why
    # nulls_first=True/False exists for cross-dialect consistency.
    for sql in (postgres_sql, databricks_sql):
        assert "NULLS FIRST" not in sql
        assert "NULLS LAST" not in sql
    assert "ORDER BY order_status" in squash(postgres_sql)
    assert "ORDER BY order_status" in squash(databricks_sql)


def test_count_measure_maps_to_count(
    squash: Callable[[str], str],
) -> None:
    """The count aggregation renders COUNT over the measure field."""
    model = _model()

    sql = model.q.calculate("order_count").compile().sql

    assert "COUNT(orders.id) AS order_count" in squash(sql)


def test_compile_query_entry_point_matches_query_compile() -> None:
    """The module entry point accepts the query and the model explicitly."""
    model = _model()
    query = model.q.calculate("revenue")

    assert compile_query(query, model).sql == query.compile().sql


def test_conflicting_measure_routes_are_rejected() -> None:
    """Measures that pin different routes for one pair cannot share a query."""
    model = _model()
    model.registry.measures["by_id"] = Measure(
        name="by_id",
        field=FieldRef(entity="orders", name="total"),
        routes={("orders", "customers"): 1},
    )
    model.registry.measures["by_region"] = Measure(
        name="by_region",
        field=FieldRef(entity="orders", name="total"),
        routes={("orders", "customers"): 0},
    )

    with pytest.raises(ValueError, match="Conflicting routes"):
        model.q.calculate("by_id").calculate("by_region").compile()


def test_cyclic_relationship_selection_is_rejected() -> None:
    """A model whose selected edges form a cycle cannot be compiled."""
    model = _model(cyclic=True)

    with pytest.raises(RelationshipCycleError, match="Relationship cycles detected"):
        model.q.calculate("revenue").compile()


def test_multi_fact_query_builds_ctes_and_merges_them(
    squash: Callable[[str], str],
) -> None:
    """Two fact entities produce two CTEs joined by FULL OUTER JOIN."""
    model = _model()
    query = (
        model.q.group_by("customers.region")
        .calculate("min_total", alias="total_revenue")
        .calculate("min_refund", alias="total_refund")
        .order_by("total_revenue", descending=True)
    )

    sql = query.compile(dialect="databricks").sql

    normalized = squash(sql)
    assert normalized.startswith("WITH orders_agg AS")
    assert "refunds_agg AS" in normalized
    assert "FULL OUTER JOIN refunds_agg" in normalized
    assert "COALESCE(orders_agg.customers__region, refunds_agg.customers__region)" in (
        normalized
    )
    assert "MIN(orders.total) AS total_revenue" in normalized
    assert "MIN(refunds.amount) AS total_refund" in normalized
    assert "ORDER BY total_revenue DESC" in normalized


def test_unreachable_entity_is_rejected() -> None:
    """An entity without a join path to the base fails clearly."""
    model = _model()
    products = _entity("products", "id", "sku")
    model.registry.entities["products"] = products

    with pytest.raises(ValueError, match="not reachable from base entity 'orders'"):
        model.q.group_by("products.sku").calculate("revenue").compile()


def test_unknown_references_are_rejected() -> None:
    """Unknown entities, fields and measures raise ValueError."""
    model = _model()

    with pytest.raises(ValueError, match="Unknown entity alias 'nope'"):
        model.q.group_by("nope.id").compile()

    with pytest.raises(ValueError, match="Unknown field 'nope'"):
        model.q.group_by("orders.nope").compile()

    with pytest.raises(ValueError, match="Unknown measure 'nope'"):
        model.q.calculate("nope").compile()


def test_unknown_ordering_alias_is_rejected() -> None:
    """Ordering by something that is not projected is an error."""
    model = _model()
    query = (
        model.q.group_by("orders.status")
        .calculate("revenue")
        .order_by("nope", descending=True)
    )

    with pytest.raises(ValueError, match="Unknown ordering alias"):
        query.compile()


def test_query_without_projections_is_rejected() -> None:
    """A query must select at least one dimension or measure."""
    model = _model()

    with pytest.raises(ValueError, match="no dimensions or measures"):
        Query(model=model).compile()


def test_unsupported_comparison_operator_is_rejected() -> None:
    """Only the comparison operators of the parser are supported."""
    model = _model()
    predicate = Comparison(
        field=FieldRef(entity="orders", name="status"),
        operator="~",
        value=Literal("paid"),
    )
    query = dataclasses.replace(model.q.calculate("revenue"), filters=(predicate,))

    with pytest.raises(ValueError, match="Unsupported comparison operator"):
        query.compile()


def test_unsupported_measure_aggregation_is_rejected() -> None:
    """Measure aggregations are validated at construction time."""
    with pytest.raises(ValueError, match="Unsupported aggregation"):
        Measure(
            name="median_total",
            field=FieldRef(entity="orders", name="total"),
            aggregation="median",
        )


def test_plan_only_joins_referenced_entities() -> None:
    """Relationships the query never uses stay out of the plan and the SQL."""
    model = _model()
    query = model.q.group_by("orders.status", "customers.region").calculate("min_total")
    context, resolved = _resolved(model, query)

    plan = plan_joins(resolved, select_edges(resolved, context), context)

    assert [step.relationship.name for step in plan.steps] == ["orders_customers_id"]
    sql = query.compile().sql
    assert "crm.regions" not in sql


def test_plan_has_no_steps_for_a_single_entity_query() -> None:
    """A query over one entity needs no join at all."""
    model = _model()
    query = model.q.group_by("orders.status").calculate("revenue")
    context, resolved = _resolved(model, query)

    plan = plan_joins(resolved, select_edges(resolved, context), context)

    assert plan.steps == ()


def test_base_entity_prefers_the_measure_entity() -> None:
    """Aggregating queries start from the fact table, not the dimension."""
    model = _model()
    query = model.q.group_by("customers.region").calculate("revenue")
    _, resolved = _resolved(model, query)

    assert choose_base_entity(resolved, referenced_entities(resolved)) == "orders"


def test_base_entity_falls_back_to_the_first_dimension() -> None:
    """Queries without measures start from the first dimension's entity."""
    model = _model()
    query = model.q.group_by("customers.region")
    _, resolved = _resolved(model, query)

    assert choose_base_entity(resolved, referenced_entities(resolved)) == "customers"


def test_referenced_entities_cover_filters_and_order_aliases() -> None:
    """Filter fields and ordering aliases contribute their entities."""
    model = _model()
    query = (
        model.q.group_by("orders.status", alias="status_label")
        .calculate("revenue")
        .filter("customers.region = 'APAC'")
        .order_by("status_label")
    )
    _, resolved = _resolved(model, query)

    assert referenced_entities(resolved) == ("orders", "customers")


def test_plan_join_paths_returns_only_the_needed_edges() -> None:
    """The path is trimmed to what connects the base to the references."""
    model = _model()
    query = model.q.group_by("customers.region").calculate("revenue")
    context, resolved = _resolved(model, query)
    edges = select_edges(resolved, context)

    paths = plan_join_paths("orders", ("orders", "customers"), edges, model.registry)

    assert [relationship.name for relationship in paths] == ["orders_customers_id"]
    assert plan_join_paths("orders", ("orders",), edges, model.registry) == ()


def test_plan_join_paths_rejects_unreachable_entities() -> None:
    """An alias without a path from the base is a hard error."""
    model = _model()
    model.registry.entities["products"] = _entity("products", "id")
    query = model.q.calculate("revenue")
    context, resolved = _resolved(model, query)
    edges = select_edges(resolved, context)

    with pytest.raises(ValueError, match="not reachable from base entity 'orders'"):
        plan_join_paths("orders", ("orders", "products"), edges, model.registry)


def test_choose_join_type_rules() -> None:
    """Join types follow cardinality and filter propagation only."""
    orders = _entity("orders", "id", "customer_id")
    customers = _entity("customers", "id")
    forward = _relationship("fwd", orders, "customer_id", customers, "id")
    backwards = _relationship("bwd", customers, "id", orders, "customer_id")
    many_to_many = _relationship("m2m", orders, "customer_id", customers, "id")
    many_to_many.cardinality = Cardinality.MANY_TO_MANY
    both_ways = _relationship("both", orders, "customer_id", customers, "id")
    both_ways.filter_direction = FilterDirection.BOTH
    one_to_one = _relationship("one", orders, "customer_id", customers, "id")
    one_to_one.cardinality = Cardinality.ONE_TO_ONE

    # ONE_TO_MANY joins with LEFT whichever end holds the base entity.
    assert choose_join_type(forward, "orders") == "LEFT"
    assert choose_join_type(forward, "customers") == "LEFT"
    assert choose_join_type(backwards, "customers") == "LEFT"
    assert choose_join_type(backwards, "orders") == "LEFT"
    # BOTH and MANY_TO_MANY stay INNER, ONE_TO_ONE stays LEFT.
    assert choose_join_type(both_ways, "orders") == "INNER"
    assert choose_join_type(both_ways, "customers") == "INNER"
    assert choose_join_type(many_to_many, "orders") == "INNER"
    assert choose_join_type(one_to_one, "orders") == "LEFT"


def test_one_to_many_always_uses_left() -> None:
    """The base end no longer changes the join type of a ONE_TO_MANY edge."""
    users = _entity("users", "id")
    orders = _entity("orders", "id", "user_id")
    users_to_orders = _relationship("users_to_orders", users, "id", orders, "user_id")

    # Every row of the many end survives a missing match, from either base.
    assert choose_join_type(users_to_orders, "users") == "LEFT"
    assert choose_join_type(users_to_orders, "orders") == "LEFT"


def test_filter_references_trigger_a_join(
    squash: Callable[[str], str],
) -> None:
    """A filter on another entity pulls that entity into the join plan."""
    model = _model()
    query = (
        model.q.group_by("orders.status")
        .calculate("revenue")
        .filter("customers.region = 'APAC'")
    )

    sql = query.compile().sql

    assert "LEFT JOIN crm.customers AS customers" in squash(sql)


def _linked_model(
    direction: FilterDirection = FilterDirection.SINGLE,
) -> SemanticModel:
    """Build a one-edge model with a configurable filter direction."""
    orders = _entity("orders", "id", "customer_id", "total", "status")
    customers = _entity("customers", "id", "region")
    link = _relationship("orders_customers", orders, "customer_id", customers, "id", 1)
    link.filter_direction = direction
    registry = SemanticRegistry(
        entities={"orders": orders, "customers": customers},
        relationships=[link],
    )
    registry.measures["revenue"] = Measure(
        name="revenue",
        field=FieldRef(entity="orders", name="total"),
        # MAX only warns about the fanout join, so this test stays about the
        # filter direction forcing an INNER JOIN.
        aggregation="max",
    )
    return SemanticModel(name="linked", registry=registry)


def test_single_direction_filter_on_source_marks_pushdown() -> None:
    """A source-side filter on a SINGLE edge could be pushed down."""
    model = _linked_model()
    query = (
        model.q.group_by("customers.region")
        .calculate("revenue")
        .filter("orders.status = 'paid'")
    )
    context, resolved = _resolved(model, query)

    plan = plan_joins(resolved, select_edges(resolved, context), context)

    step = plan.steps[0]
    assert step.filter_pushed is True
    assert step.semi_join is False
    assert step.join_type == "LEFT"


def test_both_direction_filter_on_target_forces_inner_join(
    squash: Callable[[str], str],
) -> None:
    """A target-side filter on a BOTH edge becomes an INNER JOIN plus a warning."""
    model = _linked_model(direction=FilterDirection.BOTH)
    query = (
        model.q.group_by("customers.region")
        .calculate("revenue")
        .filter("customers.region = 'APAC'")
    )
    context, resolved = _resolved(model, query)

    plan = plan_joins(resolved, select_edges(resolved, context), context)

    step = plan.steps[0]
    assert step.join_type == "INNER"
    assert step.semi_join is False
    assert any("BOTH" in warning for warning in context.report.warnings)
    assert "INNER JOIN crm.customers" in squash(query.compile().sql)


def test_left_join_filtered_on_target_warns_about_inner_semantics(
    squash: Callable[[str], str],
) -> None:
    """A LEFT join plus a target-side filter behaves like an INNER join."""
    model = _model()
    query = (
        model.q.group_by("customers.region")
        .calculate("min_total")
        .filter("customers.region = 'APAC'")
    )

    compiled = query.compile()

    # The plan keeps the LEFT JOIN and only reports the semantic downgrade.
    assert "LEFT JOIN crm.customers" in squash(compiled.sql)
    assert any(
        "behaves like an INNER JOIN" in warning for warning in compiled.report.warnings
    )


def test_route_pair_without_relationship_is_rejected() -> None:
    """A route naming a disconnected pair is a hard error."""
    model = _model()
    model.registry.entities["products"] = _entity("products", "id")
    query = model.q.calculate("revenue").route("orders", "products", 0)

    with pytest.raises(
        ValueError, match="No relationship from 'orders' to 'products' in the model"
    ):
        query.compile()


def test_route_pair_unused_by_the_query_is_rejected() -> None:
    """A route for a pair the query never touches is a hard error."""
    model = _model()
    query = (
        model.q.group_by("customers.region")
        .calculate("customer_count")
        .route("orders", "regions", 0)
    )

    with pytest.raises(ValueError, match="is not used by the query"):
        query.compile()


def test_single_fact_measures_do_not_use_a_cte(
    squash: Callable[[str], str],
) -> None:
    """Several measures on one entity keep the plain single-select shape."""
    model = _model()
    query = (
        model.q.group_by("orders.status")
        .calculate("revenue")
        .calculate("order_count")
        .order_by("revenue", descending=True)
    )

    sql = query.compile().sql

    normalized = squash(sql)
    assert not normalized.startswith("WITH")
    assert "SUM(orders.total) AS revenue" in normalized
    assert "COUNT(orders.id) AS order_count" in normalized
    assert "GROUP BY orders.status" in normalized
    assert "ORDER BY revenue DESC" in normalized


def test_multi_fact_cte_groups_by_every_dimension(
    squash: Callable[[str], str],
) -> None:
    """Each CTE groups by the dimensions it can provide."""
    model = _model()
    query = (
        model.q.group_by("orders.status", "customers.region")
        .calculate("min_total")
        .calculate("min_refund")
    )

    sql = query.compile(dialect="databricks").sql

    normalized = squash(sql)
    assert "GROUP BY orders.status, customers.region" in normalized
    assert "refunds_agg AS" in normalized
    statement = sqlglot.parse_one(sql, read="databricks")
    assert [item.alias for item in statement.expressions] == [
        "orders__status",
        "customers__region",
        "min_total",
        "min_refund",
    ]


def test_unreachable_dimension_in_strict_mode_is_rejected() -> None:
    """A dimension no CTE can provide fails in the default strict mode."""
    model = _model()
    query = (
        model.q.group_by("campaigns.name")
        .calculate("revenue")
        .calculate("refund_total")
    )

    with pytest.raises(ValueError) as excinfo:
        query.compile(dialect="databricks")

    message = str(excinfo.value)
    assert "cannot aggregate by dimension 'campaigns'" in message
    assert "'orders'" in message


def test_unreachable_dimension_can_be_nulled_in_lenient_mode(
    squash: Callable[[str], str],
) -> None:
    """Lenient mode projects NULL for the dimension and warns about it."""
    model = _model()
    query = (
        model.q.group_by("campaigns.name", alias="campaign")
        .calculate("revenue", alias="total_revenue")
        .calculate("refund_total", alias="total_refund")
    )

    context = CompileContext(
        model=model,
        query=query,
        unreachable_dimensions="null",
    )
    resolved = resolve_query(query, context)
    edges = select_edges(resolved, context)
    ctes = plan_ctes(
        resolved,
        group_measures_by_entity(resolved),
        edges,
        model.registry,
        "null",
    )
    for cte in ctes:
        for dimension in cte.null_dimensions:
            context.report.add_unreachable_dimension(
                f"Dimension {dimension.output_alias!r} is NULL for entity "
                f"{cte.entity_alias!r}"
            )

    sql = query.compile(dialect="databricks", unreachable_dimensions="null").sql

    normalized = squash(sql)
    assert "NULL AS campaign" in normalized
    assert "COALESCE(orders_agg.campaign, refunds_agg.campaign)" in normalized
    assert [
        dimension.output_alias for cte in ctes for dimension in cte.null_dimensions
    ] == ["campaign", "campaign"]
    assert any(
        "is NULL for entity" in item
        for item in context.report.unreachable_dimension_warnings
    )


def test_invalid_unreachable_dimensions_mode_is_rejected() -> None:
    """Only 'error' and 'null' are accepted."""
    model = _model()

    with pytest.raises(ValueError, match="unreachable_dimensions must be"):
        model.q.calculate("revenue").compile(unreachable_dimensions="ignore")


def test_filters_are_pushed_into_the_matching_cte(
    squash: Callable[[str], str],
) -> None:
    """Each fact CTE only receives the predicates it can evaluate."""
    model = _model()
    query = (
        model.q.group_by("customers.region")
        .calculate("min_total")
        .calculate("min_refund")
        .filter("orders.status = 'paid'")
        .filter("refunds.reason = 'damaged'")
    )
    context, resolved = _resolved(model, query)
    edges = select_edges(resolved, context)

    ctes = plan_ctes(
        resolved,
        group_measures_by_entity(resolved),
        edges,
        model.registry,
        "error",
    )

    pushed = {cte.name: len(cte.filters) for cte in ctes}
    # orders is not a dimension here, so refunds_agg cannot reach it and only
    # orders_agg receives the orders filter; this is the intended behaviour.
    assert pushed == {"orders_agg": 1, "refunds_agg": 1}

    normalized = squash(query.compile(dialect="databricks").sql)
    orders_cte, refunds_cte = normalized.split("refunds_agg AS")
    assert "orders.status = 'paid'" in orders_cte
    assert "refunds.reason = 'damaged'" not in orders_cte
    assert "refunds.reason = 'damaged'" in refunds_cte
    assert "orders.status = 'paid'" not in refunds_cte


def test_filter_pushed_to_all_reachable_ctes() -> None:
    """A filter is pushed to every CTE that can reach its entity."""
    model = _model()
    query = (
        model.q.group_by("orders.status")
        .calculate("revenue")
        .calculate("refund_total")
        .filter("orders.total > 0")
    )
    context, resolved = _resolved(model, query)
    order_filter = resolved.filters[0]
    assert isinstance(order_filter, Comparison)

    ctes = plan_ctes(
        resolved,
        group_measures_by_entity(resolved),
        select_edges(resolved, context),
        model.registry,
        "error",
    )
    pushed = {cte.name: cte.filters for cte in ctes}

    # Both CTEs join orders, so one filter lands in the WHERE clause of both.
    assert order_filter in pushed["orders_agg"]
    assert order_filter in pushed["refunds_agg"]


def test_filter_only_pushed_to_reachable_ctes() -> None:
    """A filter is not pushed to CTEs that cannot reach its entity."""
    model = _model()
    query = (
        model.q.group_by("orders.status")
        .calculate("revenue")
        .calculate("refund_total")
        .filter("refunds.reason = 'damaged'")
    )
    context, resolved = _resolved(model, query)
    refund_filter = resolved.filters[0]
    assert isinstance(refund_filter, Comparison)

    ctes = plan_ctes(
        resolved,
        group_measures_by_entity(resolved),
        select_edges(resolved, context),
        model.registry,
        "error",
    )
    pushed = {cte.name: cte.filters for cte in ctes}

    # orders_agg has no path to refunds, so it must not receive the predicate.
    assert refund_filter in pushed["refunds_agg"]
    assert refund_filter not in pushed["orders_agg"]
    assert pushed["orders_agg"] == ()


def test_or_filter_spanning_facts_is_rejected() -> None:
    """An OR across two fact entities cannot be pushed into one CTE."""
    model = _model()
    query = (
        model.q.group_by("customers.region")
        .calculate("min_total")
        .calculate("min_refund")
        .filter("orders.status = 'paid' OR refunds.reason = 'damaged'")
    )

    with pytest.raises(ValueError, match="OR filter spanning multiple fact entities"):
        query.compile(dialect="databricks")


def test_full_outer_join_uses_null_safe_equality() -> None:
    """The merge joins CTEs with IS NOT DISTINCT FROM over the dimensions."""
    model = _model()
    query = (
        model.q.group_by("customers.region")
        .calculate("min_total")
        .calculate("min_refund")
    )

    sql = query.compile(dialect="databricks").sql

    assert "IS NOT DISTINCT FROM" in sql
