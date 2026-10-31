"""Tests for the join-condition abstraction behind semantic relationships."""

from __future__ import annotations

from collections.abc import Callable

import pytest
import sqlglot
from etlalchemy.compile.compiler import _warn_expression_joins
from etlalchemy.compile.context import CompileContext
from etlalchemy.compile.report import EXPRESSION_JOIN_UNBOUND
from etlalchemy.compile.resolve import resolve_query
from etlalchemy.compile.routes import select_edges
from etlalchemy.semantic import (
    Cardinality,
    EquiJoin,
    ExpressionJoin,
    Field,
    FieldCollection,
    FieldRef,
    FilterDirection,
    Materialization,
    Measure,
    Rowset,
    SemanticEntity,
    SemanticModel,
    SemanticRegistry,
    String,
    equi_join,
    expression_join,
)
from etlalchemy.semantic.join import JoinCondition
from etlalchemy.semantic.relationship import SemanticRelationship

from semantic.builders import entity, relationship


def _parameter(value: object) -> str:
    """Return a placeholder name for one bound value."""
    return f":p{value}"


def _collection(item: SemanticEntity, *names: str) -> FieldCollection:
    """Collect fields of one entity in the given order."""
    return FieldCollection(item, tuple(item.relation.fields[name] for name in names))


def _orders() -> SemanticEntity:
    """Build an order entity with a two-column composite key."""
    rowset = Rowset(
        name="crm.orders",
        kind=Materialization.TABLE,
        fields={
            name: Field(name=name, data_type=String())
            for name in ("tenant", "id", "customer_tenant", "customer_id", "status")
        },
        primary_key=["tenant", "id"],
    )
    return SemanticEntity(id=entity("orders").id, alias="orders", relation=rowset)


def _customers() -> SemanticEntity:
    """Build a customer entity with a two-column composite key."""
    rowset = Rowset(
        name="crm.customers",
        kind=Materialization.TABLE,
        fields={
            name: Field(name=name, data_type=String())
            for name in ("tenant", "id", "name", "region")
        },
        primary_key=["tenant", "id"],
    )
    return SemanticEntity(id=entity("customers").id, alias="customers", relation=rowset)


def _patterns() -> SemanticEntity:
    """Build a tiny lookup entity holding regular expressions."""
    rowset = Rowset(
        name="crm.patterns",
        kind=Materialization.TABLE,
        fields={
            name: Field(name=name, data_type=String()) for name in ("id", "pattern")
        },
        primary_key=["id"],
    )
    return SemanticEntity(id=entity("patterns").id, alias="patterns", relation=rowset)


def test_equi_join_renders_single_column_comparison() -> None:
    """A one-column equi join renders one equality without parameters."""
    orders, customers = _orders(), _customers()
    condition = EquiJoin(
        source=_collection(orders, "tenant"),
        target=_collection(customers, "tenant"),
    )

    sql, parameters = condition.to_sql("o", "c", False, _parameter)

    assert sql == "o.tenant = c.tenant"
    assert parameters == []


def test_equi_join_renders_composite_comparison() -> None:
    """Composite keys are combined with AND in declaration order."""
    orders, customers = _orders(), _customers()
    condition = EquiJoin(
        source=_collection(orders, "tenant", "customer_id"),
        target=_collection(customers, "tenant", "id"),
    )

    sql, parameters = condition.to_sql("o", "c", True, _parameter)

    assert sql == "o.tenant = c.tenant AND o.customer_id = c.id"
    assert parameters == []


def test_equi_join_reports_composite_length_mismatch() -> None:
    """Unequal composite key lengths are rejected when the condition is built."""
    orders, customers = _orders(), _customers()

    with pytest.raises(ValueError, match="Composite key length mismatch"):
        EquiJoin(
            source=_collection(orders, "tenant", "id"),
            target=_collection(customers, "id"),
        )


def test_equi_join_reports_referenced_entities() -> None:
    """An equi join references the entities owning its field collections."""
    orders, customers = _orders(), _customers()
    condition = EquiJoin(
        source=_collection(orders, "tenant"),
        target=_collection(customers, "tenant"),
    )

    assert condition.source_entity_alias() == "orders"
    assert condition.target_entity_alias() == "customers"
    assert condition.referenced_entities() == ("orders", "customers")
    assert isinstance(condition, JoinCondition)


def test_expression_join_substitutes_aliases() -> None:
    """Both placeholders are replaced by the caller supplied aliases."""
    condition = ExpressionJoin(
        source_entity="orders",
        target_entity="patterns",
        expression="regexp_like({source}.status, {target}.pattern)",
    )

    sql, parameters = condition.to_sql("o", "p", False, _parameter)

    assert sql == "regexp_like(o.status, p.pattern)"
    assert parameters == []
    assert condition.referenced_entities() == ("orders", "patterns")


def test_expression_join_rejects_unknown_placeholders() -> None:
    """Only the documented placeholders are understood."""
    with pytest.raises(ValueError, match="Unsupported placeholders"):
        ExpressionJoin(
            source_entity="orders",
            target_entity="patterns",
            expression="regexp_like({origin}.status, {target}.pattern)",
        )


def test_relationship_exposes_field_collections_for_equi_joins() -> None:
    """Equi joins keep the familiar source and target collections."""
    orders, customers = _orders(), _customers()
    join = equi_join(
        name="orders_customers",
        source=_collection(orders, "tenant", "customer_id"),
        target=_collection(customers, "tenant", "id"),
        cardinality=Cardinality.ONE_TO_MANY,
    )

    assert isinstance(join, SemanticRelationship)
    assert join.source == _collection(orders, "tenant", "customer_id")
    assert join.target.entity is customers
    assert join.source_alias() == "orders"
    assert join.target_alias() == "customers"


def test_relationship_rejects_expression_join_collections() -> None:
    """Expression joins have no source or target field collection."""
    join = expression_join(
        name="orders_patterns",
        source_entity="orders",
        target_entity="patterns",
        expression="regexp_like({source}.status, {target}.pattern)",
        cardinality=Cardinality.MANY_TO_MANY,
    )

    with pytest.raises(AttributeError, match="source"):
        _ = join.source
    with pytest.raises(AttributeError, match="target"):
        _ = join.target
    assert join.source_alias() == "orders"
    assert join.target_alias() == "patterns"


def test_relationship_leaves_condition_validation_to_type_checking() -> None:
    """A non-condition is a typing error, not a runtime isinstance check."""
    broken = SemanticRelationship(
        name="broken",
        condition="orders.id = patterns.id",  # type: ignore[arg-type]
    )

    assert not broken.is_equi_join()
    with pytest.raises(AttributeError):
        broken.source_alias()


def test_relationship_reports_whether_it_is_an_equi_join() -> None:
    """Callers branch on is_equi_join instead of probing source with hasattr."""
    orders, customers = _orders(), _customers()
    equi = equi_join(
        name="orders_customers",
        source=_collection(orders, "customer_id"),
        target=_collection(customers, "id"),
    )
    expression = expression_join(
        name="orders_patterns",
        source_entity="orders",
        target_entity="patterns",
        expression="regexp_like({source}.status, {target}.pattern)",
    )

    assert equi.is_equi_join() is True
    assert expression.is_equi_join() is False
    assert hasattr(expression, "source") is False


def test_expression_join_rejects_malformed_placeholders() -> None:
    """Unbalanced or doubled braces cannot leak into the compiled SQL."""
    for expression in (
        "regexp_like({source.status, {target}.pattern)",
        "regexp_like({{source}}.status, {target}.pattern)",
        "regexp_like({source}.status, {target}.pattern)}",
        "regexp_like(source}, {target}.pattern)",
    ):
        with pytest.raises(ValueError, match="malformed placeholders"):
            ExpressionJoin(
                source_entity="orders",
                target_entity="patterns",
                expression=expression,
            )


def test_expression_join_rejects_format_modifiers() -> None:
    """Conversions and format specs are not placeholders of the first version."""
    with pytest.raises(ValueError, match="Unsupported placeholders"):
        ExpressionJoin(
            source_entity="orders",
            target_entity="patterns",
            expression="regexp_like({source!r}.status, {target}.pattern)",
        )


def _model() -> SemanticModel:
    """Build a model joining orders to patterns through an expression.

    The edge is ONE_TO_ONE so these join tests are not rejected by the fanout
    check; MANY_TO_MANY detection has its own coverage in ``test_fanout.py``.
    """
    orders = _orders()
    patterns = _patterns()
    registry = SemanticRegistry(
        entities={"orders": orders, "patterns": patterns},
        relationships=[
            expression_join(
                name="orders_patterns",
                source_entity="orders",
                target_entity="patterns",
                expression="regexp_like({source}.status, {target}.pattern)",
                cardinality=Cardinality.ONE_TO_ONE,
            )
        ],
    )
    registry.measures["revenue"] = Measure(
        name="revenue", field=FieldRef(entity="orders", name="id")
    )
    return SemanticModel(name="crm", registry=registry)


def test_expression_join_compiles_into_the_on_clause(
    squash: Callable[[str], str],
) -> None:
    """The compiled join uses the rendered expression as its condition."""
    model = _model()
    query = model.q.group_by("patterns.pattern").calculate("revenue")

    sql = query.compile().sql

    statement = sqlglot.parse_one(sql, read="postgres")
    joined = statement.args["joins"][0]
    on_clause = squash(joined.args["on"].sql())
    assert "REGEXP_LIKE(orders.status, patterns.pattern)" in on_clause


def test_expression_join_rejects_bidirectional_filters_at_construction() -> None:
    """The first version only supports SINGLE direction expression joins."""
    with pytest.raises(ValueError, match="only support filter_direction='SINGLE'"):
        expression_join(
            name="orders_patterns",
            source_entity="orders",
            target_entity="patterns",
            expression="regexp_like({source}.status, {target}.pattern)",
            filter_direction=FilterDirection.BOTH,
        )


def test_expression_join_warns_about_unbound_literals() -> None:
    """A parameterised compile cannot reach an opaque expression, so it warns."""
    model = _model()
    query = model.q.group_by("patterns.pattern").calculate("revenue")
    context = CompileContext(model=model, query=query, inline_literals=False)
    resolved = resolve_query(query, context)

    _warn_expression_joins(select_edges(resolved, context), context)

    events = context.report.with_code(EXPRESSION_JOIN_UNBOUND)
    assert [event.relationship for event in events] == ["orders_patterns"]
    assert events[0].severity == "warning"
    assert events[0].phase == "routes"
    assert "does not bind literals" in events[0].message


def test_expression_join_stays_silent_with_inline_literals() -> None:
    """With literals inlined there is nothing to warn about."""
    model = _model()
    query = model.q.group_by("patterns.pattern").calculate("revenue")
    context = CompileContext(model=model, query=query)
    resolved = resolve_query(query, context)

    _warn_expression_joins(select_edges(resolved, context), context)

    assert context.report.with_code(EXPRESSION_JOIN_UNBOUND) == ()


def test_equi_join_stays_silent_when_literals_are_parameterized(
    squash: Callable[[str], str],
) -> None:
    """Equi joins never need the expression warning."""
    orders, customers = _orders(), _customers()
    model = SemanticModel(
        name="crm",
        registry=SemanticRegistry(
            entities={"orders": orders, "customers": customers},
            relationships=[
                equi_join(
                    name="orders_customers",
                    source=_collection(orders, "customer_id"),
                    target=_collection(customers, "id"),
                    cardinality=Cardinality.ONE_TO_MANY,
                )
            ],
        ),
    )
    model.registry.measures["revenue"] = Measure(
        name="revenue",
        field=FieldRef(entity="orders", name="id"),
        # MAX only warns about a fanout join.
        aggregation="max",
    )
    query = model.q.group_by("customers.name").calculate("revenue")

    sql = query.compile(inline_literals=False).sql

    assert "ON orders.customer_id = customers.id" in squash(sql)


def test_plain_relationship_still_joins_on_ids(
    squash: Callable[[str], str],
) -> None:
    """The legacy helper keeps producing equality joins."""
    a, b = entity("a"), entity("b")
    model = SemanticModel(
        name="m",
        registry=SemanticRegistry(
            entities={"a": a, "b": b},
            # One b row to many a rows, so the measure on ``a`` sits on the
            # many end and the join cannot fan it out.
            relationships=[relationship("ab", b, a)],
        ),
    )
    model.registry.measures["count"] = Measure(
        name="count", field=FieldRef(entity="a", name="id"), aggregation="count"
    )
    query = model.q.group_by("b.id").calculate("count")

    sql = query.compile().sql

    assert "b.id = a.id" in squash(sql) or "a.id = b.id" in squash(sql)
