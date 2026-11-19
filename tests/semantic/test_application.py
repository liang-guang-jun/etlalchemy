"""Tests for the semantic application use cases."""

from __future__ import annotations

from uuid import uuid4

import pytest
from etlalchemy.catalog.aggregates.errors import UnknownTableError
from etlalchemy.semantic.aggregates.errors import DiscardedError, InvalidRelationshipError
from etlalchemy.semantic.aggregates.types import Cardinality, FieldRef, FilterDirection
from etlalchemy.semantic.application import ModelApplication

from tests.semantic.support import FakeCatalogView


async def test_creating_a_model_returns_a_readable_aggregate(
    model_app: ModelApplication,
) -> None:
    """A created model is stored and can be read back."""
    model_id = await model_app.create_model("sales", "Revenue model")

    model = await model_app.get_model(model_id)

    assert model.name == "sales"
    assert model.description == "Revenue model"


async def test_changing_a_model_stores_the_new_attributes(
    model_app: ModelApplication,
) -> None:
    """A change is persisted."""
    model_id = await model_app.create_model("sales")

    await model_app.change_model(model_id, name="revenue")

    assert (await model_app.get_model(model_id)).name == "revenue"


async def test_adding_an_entity_requires_a_catalog_table(
    model_app: ModelApplication,
    catalog_view: FakeCatalogView,
) -> None:
    """An unknown table is rejected before the model changes."""
    model_id = await model_app.create_model("sales")
    missing = uuid4()

    with pytest.raises(UnknownTableError, match=str(missing)):
        await model_app.add_entity(model_id, "orders", missing)

    assert (await model_app.get_model(model_id)).entities == {}


async def test_adding_an_entity_records_it_with_its_table(
    model_app: ModelApplication,
    catalog_view: FakeCatalogView,
) -> None:
    """A known table is accepted and the entity keeps its id."""
    model_id = await model_app.create_model("sales")
    table_id = catalog_view.add_table("orders", "id", "total")

    await model_app.add_entity(model_id, "orders", table_id)

    entity = (await model_app.get_model(model_id)).entities["orders"]
    assert entity.table_id == table_id


async def test_changing_an_entity_table_requires_a_catalog_table(
    model_app: ModelApplication,
    catalog_view: FakeCatalogView,
) -> None:
    """An unknown table is rejected when repointing an entity."""
    model_id = await model_app.create_model("sales")
    await model_app.add_entity(model_id, "orders", catalog_view.add_table("orders", "id"))

    with pytest.raises(UnknownTableError):
        await model_app.change_entity_table(model_id, "orders", uuid4())


async def test_a_relationship_may_only_reference_catalog_fields(
    model_app: ModelApplication,
    catalog_view: FakeCatalogView,
) -> None:
    """A field that the referenced table does not have is rejected."""
    model_id = await model_app.create_model("sales")
    customers = catalog_view.add_table("customers", "id")
    orders = catalog_view.add_table("orders", "id", "customer_id")
    await model_app.add_entity(model_id, "customers", customers)
    await model_app.add_entity(model_id, "orders", orders)

    with pytest.raises(InvalidRelationshipError, match="ghost"):
        await model_app.add_relationship(
            model_id,
            [FieldRef(entity="customers", field="id")],
            [FieldRef(entity="orders", field="ghost")],
            Cardinality.ONE_TO_MANY,
            FilterDirection.SINGLE,
        )


async def test_a_relationship_may_only_reference_model_entities(
    model_app: ModelApplication,
    catalog_view: FakeCatalogView,
) -> None:
    """A reference to an entity outside the model is rejected."""
    model_id = await model_app.create_model("sales")
    await model_app.add_entity(model_id, "orders", catalog_view.add_table("orders", "id"))

    with pytest.raises(InvalidRelationshipError, match="ghosts"):
        await model_app.add_relationship(
            model_id,
            [FieldRef(entity="ghosts", field="id")],
            [FieldRef(entity="orders", field="id")],
            Cardinality.ONE_TO_ONE,
            FilterDirection.SINGLE,
        )


async def test_the_full_flow_is_recorded_in_one_aggregate(
    model_app: ModelApplication,
    catalog_view: FakeCatalogView,
) -> None:
    """Entities, relationships, diagrams and nodes build up in one model."""
    model_id = await model_app.create_model("sales")
    customers = catalog_view.add_table("customers", "id")
    orders = catalog_view.add_table("orders", "id", "customer_id")
    await model_app.add_entity(model_id, "customers", customers)
    await model_app.add_entity(model_id, "orders", orders)

    relationship_id = await model_app.add_relationship(
        model_id,
        [FieldRef(entity="customers", field="id")],
        [FieldRef(entity="orders", field="customer_id")],
        Cardinality.ONE_TO_MANY,
        FilterDirection.BOTH,
        priority=4,
    )
    await model_app.add_diagram(model_id, "detail", order=1)
    await model_app.place_node(model_id, "detail", "orders", 10.0, 20.0)
    await model_app.move_node(model_id, "detail", "orders", 30.0, 40.0)

    model = await model_app.get_model(model_id)
    assert sorted(model.entities) == ["customers", "orders"]
    relationship = model.relationships[relationship_id]
    assert relationship.from_refs == (("customers", "id"),)
    assert relationship.to_refs == (("orders", "customer_id"),)
    assert relationship.priority == 4
    assert model.diagrams["detail"].order == 1
    node = model.diagrams["detail"].nodes["orders"]
    assert (node.x, node.y) == (30.0, 40.0)
    assert set(model.diagrams["All"].nodes) == {"customers", "orders"}


async def test_changing_a_relationship_validates_the_new_fields(
    model_app: ModelApplication,
    catalog_view: FakeCatalogView,
) -> None:
    """A changed side is validated against the catalog too."""
    model_id = await model_app.create_model("sales")
    await model_app.add_entity(model_id, "customers", catalog_view.add_table("customers", "id"))
    orders = catalog_view.add_table("orders", "id", "customer_id")
    await model_app.add_entity(model_id, "orders", orders)
    relationship_id = await model_app.add_relationship(
        model_id,
        [FieldRef(entity="customers", field="id")],
        [FieldRef(entity="orders", field="customer_id")],
        Cardinality.ONE_TO_MANY,
        FilterDirection.SINGLE,
    )

    with pytest.raises(InvalidRelationshipError, match="missing"):
        await model_app.change_relationship(
            model_id,
            relationship_id,
            to_refs=[FieldRef(entity="orders", field="missing")],
        )


async def test_a_discarded_model_rejects_further_commands(
    model_app: ModelApplication,
    catalog_view: FakeCatalogView,
) -> None:
    """Everything after ``discard_model`` is rejected."""
    model_id = await model_app.create_model("sales")

    await model_app.discard_model(model_id)

    with pytest.raises(DiscardedError):
        await model_app.add_entity(model_id, "orders", catalog_view.add_table("orders", "id"))
    with pytest.raises(DiscardedError):
        await model_app.add_diagram(model_id, "detail")
