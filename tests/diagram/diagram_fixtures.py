"""Model fixtures shared by the diagram tests."""

from __future__ import annotations

from uuid import UUID, uuid5

from etlalchemy.semantic import (
    Cardinality,
    DataType,
    Decimal,
    Field,
    FieldCollection,
    FilterDirection,
    Integer,
    Materialization,
    Rowset,
    SemanticEntity,
    SemanticModel,
    SemanticRegistry,
    SemanticRelationship,
    String,
    equi_join,
)

NAMESPACE = UUID("00000000-0000-0000-0000-000000000000")

Column = tuple[str, DataType]


def make_entity(name: str, columns: list[Column]) -> SemanticEntity:
    """Build a table-backed entity displayed as ``name``."""
    return _entity(name, columns, Materialization.TABLE)


def query_entity(name: str, columns: list[Column]) -> SemanticEntity:
    """Build an entity backed by a query rather than by a table."""
    return _entity(name, columns, Materialization.QUERY)


def _entity(
    name: str,
    columns: list[Column],
    kind: Materialization,
) -> SemanticEntity:
    """Build an entity of the given rowset kind, displayed as ``name``."""
    fields = {
        column: Field(name=column, data_type=data_type) for column, data_type in columns
    }
    rowset = Rowset(
        name=f"public.{name.lower()}",
        kind=kind,
        fields=fields,
        primary_key=["id"] if "id" in fields else None,
    )
    return SemanticEntity(
        id=uuid5(NAMESPACE, name),
        alias=name.lower(),
        relation=rowset,
    )


def relationship(
    name: str,
    source: SemanticEntity,
    source_column: str,
    target: SemanticEntity,
    target_column: str,
    *,
    cardinality: Cardinality = Cardinality.ONE_TO_MANY,
    filter_direction: FilterDirection = FilterDirection.SINGLE,
    priority: int = 0,
) -> SemanticRelationship:
    """Build a single-column relationship between two entities."""
    return equi_join(
        name=name,
        source=FieldCollection(source, (source.relation.fields[source_column],)),
        target=FieldCollection(target, (target.relation.fields[target_column],)),
        cardinality=cardinality,
        filter_direction=filter_direction,
        priority=priority,
    )


def make_model() -> SemanticModel:
    """Build the three-entity sales model the diagram tests draw."""
    customer = make_entity(
        "Customer",
        [("id", Integer()), ("name", String())],
    )
    order = make_entity(
        "Order",
        [
            ("id", Integer()),
            ("customer_id", Integer()),
            ("total", Decimal(10, 2)),
        ],
    )
    payment = make_entity(
        "Payment",
        [("id", Integer()), ("order_id", Integer())],
    )
    return SemanticModel(
        name="Sales",
        registry=SemanticRegistry(
            entities={
                "Customer": customer,
                "Order": order,
                "Payment": payment,
            },
            relationships=[
                relationship("customer_orders", customer, "id", order, "customer_id"),
                relationship(
                    "order_payments",
                    order,
                    "id",
                    payment,
                    "order_id",
                    priority=2,
                ),
            ],
        ),
    )


def model_of(
    entities: dict[str, SemanticEntity],
    relationships: list[SemanticRelationship] | None = None,
) -> SemanticModel:
    """Build a model from a registry mapping and its relationships."""
    return SemanticModel(
        name="Test",
        registry=SemanticRegistry(
            entities=dict(entities),
            relationships=list(relationships or ()),
        ),
    )


def entity_id(model: SemanticModel, name: str) -> str:
    """Return the diagram id of the entity registered under ``name``."""
    return str(model.registry.entities[name].id)
