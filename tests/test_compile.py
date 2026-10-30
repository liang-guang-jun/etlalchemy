"""End-to-end tests for the semantic query compiler."""

from __future__ import annotations

import dataclasses
from uuid import UUID, uuid5

import pytest
import sqlglot
from etlalchemy.compile import compile_query
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


def _squash(sql: str) -> str:
    """Collapse whitespace so assertions survive pretty formatting."""
    return " ".join(sql.split())


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
    return SemanticModel(name="crm", registry=registry)


def test_compiles_a_dimension_and_measure_with_limit() -> None:
    """A single-entity query selects, groups, orders and limits."""
    model = _model()
    query = model.q.group_by("orders.status").calculate("revenue").limit(10)

    sql, parameters = query.compile()

    statement = sqlglot.parse_one(sql, read="postgres")
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
    assert "SUM(orders.total) AS revenue" in _squash(sql)
    assert "GROUP BY orders.status" in _squash(sql)
    assert "LIMIT 10" in _squash(sql)
    assert parameters == []


def test_dimension_alias_is_used_as_the_output_name() -> None:
    """A dimension alias becomes the projected column name and the ordering key."""
    model = _model()
    query = (
        model.q.group_by("orders.status", alias="order_status")
        .calculate("revenue")
        .order_by("order_status")
    )

    sql, _ = query.compile()

    statement = sqlglot.parse_one(sql, read="postgres")
    assert [item.alias for item in statement.expressions] == [
        "order_status",
        "revenue",
    ]
    assert "ORDER BY order_status" in _squash(sql)


def test_order_by_rejects_an_unknown_dimension_alias() -> None:
    """The default dimension alias is 'entity__name', not 'entity.name'."""
    model = _model()
    query = model.q.group_by("orders.status").order_by("orders.status")

    with pytest.raises(ValueError, match="Unknown ordering alias"):
        query.compile()


def test_compiles_without_group_by_when_there_are_no_dimensions() -> None:
    """A pure aggregate query has no GROUP BY clause."""
    model = _model()

    sql, _ = model.q.calculate("revenue").compile()

    assert "GROUP BY" not in _squash(sql)
    assert "SUM(orders.total) AS revenue" in _squash(sql)


def test_compiles_an_inner_join_when_the_base_is_on_the_many_side() -> None:
    """The measure entity is the base, so the join walks back with INNER."""
    model = _model()

    sql, _ = model.q.group_by("orders.status").calculate("customer_count").compile()

    statement = sqlglot.parse_one(sql, read="postgres")
    joins = statement.args.get("joins")
    assert joins is not None
    assert len(joins) == 1
    # The base (customers) is the target end of the ONE_TO_MANY edge, so orders
    # is joined with INNER and unmatched orders are dropped by design.
    assert "INNER JOIN crm.orders AS orders" in _squash(sql)
    assert "ON orders.customer_id = customers.id" in _squash(sql)
    assert "COUNT(customers.id) AS customer_count" in _squash(sql)


def test_compiles_a_left_join_from_the_base_to_the_many_side() -> None:
    """A fact-table base keeps all its rows when joining a dimension."""
    model = _model()

    sql, _ = model.q.group_by("customers.region").calculate("revenue").compile()

    assert "LEFT JOIN crm.customers AS customers" in _squash(sql)
    assert "ON orders.customer_id = customers.id" in _squash(sql)


def test_query_routes_pick_a_different_relationship() -> None:
    """An explicit route switches the join to the lower-priority edge."""
    model = _model()
    query = (
        model.q.group_by("orders.status")
        .calculate("customer_count")
        .route("orders", "customers", 0)
    )

    sql, _ = query.compile()

    assert "ON orders.region = customers.region" in _squash(sql)
    assert "customer_id" not in _squash(sql)


def test_literals_are_inlined_by_default() -> None:
    """The default mode inlines literals and returns no parameters."""
    model = _model()
    query = (
        model.q.group_by("orders.status")
        .calculate("revenue")
        .filter("orders.status = 'paid'")
    )

    sql, parameters = query.compile()

    assert "'paid'" in _squash(sql)
    assert "%(param0)s" not in sql
    assert parameters == []


def test_bind_literals_returns_named_parameters() -> None:
    """Bound literals become placeholders with a name-to-value mapping."""
    model = _model()
    query = (
        model.q.group_by("orders.status")
        .calculate("revenue")
        .filter("orders.status = 'paid'")
    )

    sql, parameters = query.compile(bind_literals=True)

    assert parameters == {"param0": "paid"}
    assert "%(param0)s" in sql
    assert "'paid'" not in sql

    duckdb_sql, duckdb_parameters = query.compile(dialect="duckdb", bind_literals=True)
    assert duckdb_parameters == {"param0": "paid"}
    assert "$param0" in duckdb_sql


def test_logical_predicates_bind_both_literals() -> None:
    """An AND predicate binds every literal in order."""
    model = _model()
    query = (
        model.q.group_by("orders.status")
        .calculate("revenue")
        .filter("orders.status = 'paid' AND orders.total > 100")
    )

    sql, parameters = query.compile(bind_literals=True)

    assert parameters == {"param0": "paid", "param1": 100}
    assert "%(param0)s" in sql
    assert "%(param1)s" in sql
    assert "AND" in _squash(sql)


def test_pretty_controls_line_breaks() -> None:
    """Pretty output spans lines; compact output stays on one line."""
    model = _model()
    query = model.q.group_by("orders.status").calculate("revenue").limit(10)

    pretty_sql, _ = query.compile(pretty=True)
    compact_sql, _ = query.compile(pretty=False)

    assert "\n" in pretty_sql
    assert "\n" not in compact_sql


def test_order_by_uses_the_measure_alias() -> None:
    """Ordering by a measure alias renders the alias in ORDER BY."""
    model = _model()

    sql, _ = (
        model.q.group_by("orders.status")
        .calculate("revenue")
        .order_by("revenue", descending=True)
        .compile()
    )

    assert "ORDER BY revenue DESC" in _squash(sql)


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
        sql, _ = query.compile(dialect=dialect)
        assert "NULLS FIRST" not in sql
        assert "NULLS LAST" not in sql


def test_nulls_first_false_renders_nulls_last_for_both_directions() -> None:
    """nulls_first=False puts NULLS LAST on ASC and DESC terms alike."""
    model = _model()
    query = _ordered_query(model)

    sql, _ = query.compile(nulls_first=False)
    normalized = _squash(sql)

    assert "order_status NULLS LAST" in normalized
    assert "revenue DESC NULLS LAST" in normalized
    assert "NULLS FIRST" not in normalized

    # An explicit placement is identical on every dialect.
    databricks_sql, _ = query.compile(dialect="databricks", nulls_first=False)
    assert (
        _squash(databricks_sql).split("ORDER BY")[1] == normalized.split("ORDER BY")[1]
    )


def test_nulls_first_true_renders_nulls_first_for_both_directions() -> None:
    """nulls_first=True puts NULLS FIRST on ASC and DESC terms alike."""
    model = _model()
    query = _ordered_query(model)

    sql, _ = query.compile(nulls_first=True)
    normalized = _squash(sql)

    assert "order_status NULLS FIRST" in normalized
    assert "revenue DESC NULLS FIRST" in normalized
    assert "NULLS LAST" not in normalized


def test_default_null_placement_depends_on_the_dialect() -> None:
    """With nulls_first=None the database default decides where NULLs sort."""
    model = _model()
    query = _ordered_query(model)

    postgres_sql, _ = query.compile(dialect="postgres")
    databricks_sql, _ = query.compile(dialect="databricks")

    # No NULLS clause is rendered, so the dialects keep their own defaults:
    # ASC sorts NULLs last on Postgres but first on Databricks. That is why
    # nulls_first=True/False exists for cross-dialect consistency.
    for sql in (postgres_sql, databricks_sql):
        assert "NULLS FIRST" not in sql
        assert "NULLS LAST" not in sql
    assert "ORDER BY order_status" in _squash(postgres_sql)
    assert "ORDER BY order_status" in _squash(databricks_sql)


def test_count_measure_maps_to_count() -> None:
    """The count aggregation renders COUNT over the measure field."""
    model = _model()

    sql, _ = model.q.calculate("order_count").compile()

    assert "COUNT(orders.id) AS order_count" in _squash(sql)


def test_compile_query_entry_point_matches_query_compile() -> None:
    """The module entry point accepts the query and the model explicitly."""
    model = _model()
    query = model.q.calculate("revenue")

    assert compile_query(query, model) == query.compile()


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


def test_multi_fact_query_builds_ctes_and_merges_them() -> None:
    """Two fact entities produce two CTEs joined by FULL OUTER JOIN."""
    model = _model()
    query = (
        model.q.group_by("customers.region")
        .calculate("revenue", alias="total_revenue")
        .calculate("refund_total", alias="total_refund")
        .order_by("total_revenue", descending=True)
    )

    sql, _ = query.compile(dialect="databricks")

    normalized = _squash(sql)
    assert normalized.startswith("WITH orders_agg AS")
    assert "refunds_agg AS" in normalized
    assert "FULL OUTER JOIN refunds_agg" in normalized
    assert "COALESCE(orders_agg.customers__region, refunds_agg.customers__region)" in (
        normalized
    )
    assert "SUM(orders.total) AS total_revenue" in normalized
    assert "SUM(refunds.amount) AS total_refund" in normalized
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
    query = model.q.group_by("orders.status", "customers.region").calculate("revenue")
    context, resolved = _resolved(model, query)

    plan = plan_joins(resolved, select_edges(resolved, context), context)

    assert [step.relationship.name for step in plan.steps] == ["orders_customers_id"]
    sql, _ = query.compile()
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
    """Join types follow cardinality, direction and filter propagation."""
    orders = _entity("orders", "id", "customer_id")
    customers = _entity("customers", "id")
    forward = _relationship("fwd", orders, "customer_id", customers, "id")
    backwards = _relationship("bwd", customers, "id", orders, "customer_id")
    many_to_many = _relationship("m2m", orders, "customer_id", customers, "id")
    many_to_many.cardinality = Cardinality.MANY_TO_MANY
    both_ways = _relationship("both", orders, "customer_id", customers, "id")
    both_ways.filter_direction = FilterDirection.BOTH

    assert choose_join_type(forward, "orders") == "LEFT"
    assert choose_join_type(forward, "customers") == "INNER"
    assert choose_join_type(backwards, "customers") == "LEFT"
    assert choose_join_type(many_to_many, "orders") == "INNER"
    assert choose_join_type(both_ways, "orders") == "INNER"


def test_join_type_is_inner_when_base_is_target() -> None:
    """Base on the target end of a ONE_TO_MANY edge uses INNER JOIN."""
    users = _entity("users", "id")
    orders = _entity("orders", "id", "user_id")
    users_to_orders = _relationship("users_to_orders", users, "id", orders, "user_id")

    # Rows on the target end without a matching source row are dropped on
    # purpose; reversing the relationship keeps them instead.
    assert choose_join_type(users_to_orders, "orders") == "INNER"


def test_filter_references_trigger_a_join() -> None:
    """A filter on another entity pulls that entity into the join plan."""
    model = _model()
    query = (
        model.q.group_by("orders.status")
        .calculate("revenue")
        .filter("customers.region = 'APAC'")
    )

    sql, _ = query.compile()

    assert "LEFT JOIN crm.customers AS customers" in _squash(sql)


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
        name="revenue", field=FieldRef(entity="orders", name="total")
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


def test_both_direction_filter_on_target_forces_inner_join() -> None:
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
    assert "INNER JOIN crm.customers" in _squash(query.compile()[0])


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


def test_single_fact_measures_do_not_use_a_cte() -> None:
    """Several measures on one entity keep the plain single-select shape."""
    model = _model()
    query = (
        model.q.group_by("orders.status")
        .calculate("revenue")
        .calculate("order_count")
        .order_by("revenue", descending=True)
    )

    sql, _ = query.compile()

    normalized = _squash(sql)
    assert not normalized.startswith("WITH")
    assert "SUM(orders.total) AS revenue" in normalized
    assert "COUNT(orders.id) AS order_count" in normalized
    assert "GROUP BY orders.status" in normalized
    assert "ORDER BY revenue DESC" in normalized


def test_multi_fact_cte_groups_by_every_dimension() -> None:
    """Each CTE groups by the dimensions it can provide."""
    model = _model()
    query = (
        model.q.group_by("orders.status", "customers.region")
        .calculate("revenue")
        .calculate("order_count")
        .calculate("refund_total")
    )

    sql, _ = query.compile(dialect="databricks")

    normalized = _squash(sql)
    assert "GROUP BY orders.status, customers.region" in normalized
    assert "refunds_agg AS" in normalized
    statement = sqlglot.parse_one(sql, read="databricks")
    assert [item.alias for item in statement.expressions] == [
        "orders__status",
        "customers__region",
        "revenue",
        "order_count",
        "refund_total",
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


def test_unreachable_dimension_can_be_nulled_in_lenient_mode() -> None:
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

    sql, _ = query.compile(dialect="databricks", unreachable_dimensions="null")

    normalized = _squash(sql)
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


def test_filters_are_pushed_into_the_matching_cte() -> None:
    """Each fact CTE only receives the predicates it can evaluate."""
    model = _model()
    query = (
        model.q.group_by("customers.region")
        .calculate("revenue")
        .calculate("refund_total")
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

    normalized = _squash(query.compile(dialect="databricks")[0])
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
        .calculate("revenue")
        .calculate("refund_total")
        .filter("orders.status = 'paid' OR refunds.reason = 'damaged'")
    )

    with pytest.raises(ValueError, match="OR filter spanning multiple fact entities"):
        query.compile(dialect="databricks")


def test_full_outer_join_uses_null_safe_equality() -> None:
    """The merge joins CTEs with IS NOT DISTINCT FROM over the dimensions."""
    model = _model()
    query = (
        model.q.group_by("customers.region")
        .calculate("revenue")
        .calculate("refund_total")
    )

    sql, _ = query.compile(dialect="databricks")

    assert "IS NOT DISTINCT FROM" in sql
