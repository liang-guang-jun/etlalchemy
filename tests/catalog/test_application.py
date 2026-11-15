"""Tests for the catalog application use cases."""

from uuid import uuid4

import pytest
from eventsourcing.application import AggregateNotFoundError

from etlalchemy.catalog import Catalog, CatalogApplication, DuplicateSchemaError
from etlalchemy.catalog.aggregates.errors import (
    DuplicateFieldError,
    DuplicateTableError,
    UnknownSchemaError,
)
from etlalchemy.catalog.aggregates.schema import Schema
from etlalchemy.catalog.aggregates.table import Table
from etlalchemy.catalog.aggregates.types import DataType


@pytest.fixture
def app(catalog_app: CatalogApplication) -> CatalogApplication:
    """Returns a started application backed by a temporary event store."""
    return catalog_app


async def test_create_catalog_persists_a_started_event(app: CatalogApplication) -> None:
    """create_catalog() saves the new aggregate and returns its ID."""
    catalog_id = await app.create_catalog("analytics", "Analytics warehouse")

    catalog = await app.get_catalog(catalog_id)
    assert isinstance(catalog, Catalog)
    assert catalog.name == "analytics"
    assert catalog.description == "Analytics warehouse"
    assert catalog.version == 1
    assert len(list(await app.events.get(originator_id=catalog_id))) == 1


async def test_get_catalog_raises_for_an_unknown_id(app: CatalogApplication) -> None:
    """Reading an aggregate that was never saved raises AggregateNotFoundError."""
    with pytest.raises(AggregateNotFoundError):
        await app.get_catalog(uuid4())


async def test_create_schema_saves_the_catalog_and_the_schema(app: CatalogApplication) -> None:
    """Creating a schema registers it in the catalog in one unit of work."""
    catalog_id = await app.create_catalog("analytics")

    schema_id = await app.create_schema(catalog_id, "sales", "Sales data")

    catalog = await app.get_catalog(catalog_id)
    assert catalog.schemas == {"sales": schema_id}
    assert catalog.version == 2
    schema = await app.get_schema(catalog_id, "sales")
    assert isinstance(schema, Schema)
    assert schema.id == schema_id
    assert schema.catalog_id == catalog_id
    assert schema.description == "Sales data"
    assert schema.version == 1


async def test_create_schema_rejects_duplicates_without_persisting(
    app: CatalogApplication,
) -> None:
    """A duplicate schema name leaves the catalog and event store untouched."""
    catalog_id = await app.create_catalog("analytics")
    await app.create_schema(catalog_id, "sales")

    with pytest.raises(DuplicateSchemaError, match="sales"):
        await app.create_schema(catalog_id, "sales")

    catalog = await app.get_catalog(catalog_id)
    assert list(catalog.schemas) == ["sales"]
    assert catalog.version == 2


async def test_remove_schema_unregisters_it_from_the_catalog(app: CatalogApplication) -> None:
    """Removing a schema removes the name from the catalog registry."""
    catalog_id = await app.create_catalog("analytics")
    await app.create_schema(catalog_id, "sales")

    await app.remove_schema(catalog_id, "sales")

    assert (await app.get_catalog(catalog_id)).schemas == {}


async def test_add_table_registers_it_in_the_schema(app: CatalogApplication) -> None:
    """Creating a table saves the schema and the table in one unit of work."""
    catalog_id = await app.create_catalog("analytics")
    await app.create_schema(catalog_id, "sales")

    table_id = await app.add_table(catalog_id, "sales", "orders")

    schema = await app.get_schema(catalog_id, "sales")
    assert schema.tables == {"orders": table_id}
    assert schema.version == 2
    table = await app.get_table(catalog_id, "sales", "orders")
    assert isinstance(table, Table)
    assert table.schema_id == schema.id


async def test_add_table_rejects_duplicates_without_persisting(app: CatalogApplication) -> None:
    """A duplicate table name leaves the schema untouched."""
    catalog_id = await app.create_catalog("analytics")
    await app.create_schema(catalog_id, "sales")
    await app.add_table(catalog_id, "sales", "orders")

    with pytest.raises(DuplicateTableError, match="orders"):
        await app.add_table(catalog_id, "sales", "orders")

    assert (await app.get_schema(catalog_id, "sales")).version == 2


async def test_add_table_rejects_an_unknown_schema(app: CatalogApplication) -> None:
    """A table can only be added through a schema registered in the catalog."""
    catalog_id = await app.create_catalog("analytics")

    with pytest.raises(UnknownSchemaError, match="sales"):
        await app.add_table(catalog_id, "sales", "orders")


async def test_remove_table_unregisters_it_from_the_schema(app: CatalogApplication) -> None:
    """Removing a table removes the name from the schema registry."""
    catalog_id = await app.create_catalog("analytics")
    await app.create_schema(catalog_id, "sales")
    await app.add_table(catalog_id, "sales", "orders")

    await app.remove_table(catalog_id, "sales", "orders")

    assert (await app.get_schema(catalog_id, "sales")).tables == {}


async def test_field_use_cases_update_the_table(app: CatalogApplication) -> None:
    """Field use cases are persisted on the table aggregate."""
    catalog_id = await app.create_catalog("analytics")
    await app.create_schema(catalog_id, "sales")
    await app.add_table(catalog_id, "sales", "orders")

    await app.add_field(catalog_id, "sales", "orders", "id", "integer", nullable=False)
    await app.add_field(catalog_id, "sales", "orders", "note", "text")
    await app.change_field(catalog_id, "sales", "orders", "note", data_type="varchar")
    await app.remove_field(catalog_id, "sales", "orders", "note")

    table = await app.get_table(catalog_id, "sales", "orders")
    assert list(table.fields) == ["id"]
    assert str(table.fields["id"].data_type) == "integer"
    assert table.fields["id"].nullable is False
    assert table.version == 5


async def test_rejected_field_use_case_does_not_persist_anything(
    app: CatalogApplication,
) -> None:
    """A failing use case leaves the stored aggregate untouched."""
    catalog_id = await app.create_catalog("analytics")
    await app.create_schema(catalog_id, "sales")
    await app.add_table(catalog_id, "sales", "orders")
    await app.add_field(catalog_id, "sales", "orders", "id", "integer")

    with pytest.raises(DuplicateFieldError, match="id"):
        await app.add_field(catalog_id, "sales", "orders", "id", "text")

    table = await app.get_table(catalog_id, "sales", "orders")
    assert table.fields["id"].data_type == DataType.parse("integer")
    assert table.version == 2


async def test_children_can_be_addressed_by_id(app: CatalogApplication) -> None:
    """The use cases accept the ids the create use cases return."""
    catalog_id = await app.create_catalog("analytics")
    schema_id = await app.create_schema(catalog_id, "sales")

    table_id = await app.add_table(catalog_id, schema_id, "orders")
    await app.add_field(catalog_id, schema_id, table_id, "id", "integer", nullable=False)

    assert (await app.get_schema(catalog_id, schema_id)).name == "sales"
    table = await app.get_table(catalog_id, str(schema_id), str(table_id))
    assert table.id == table_id
    assert list(table.fields) == ["id"]


async def test_ids_survive_a_rename(app: CatalogApplication) -> None:
    """Ids keep addressing a child after its name changes."""
    catalog_id = await app.create_catalog("analytics")
    schema_id = await app.create_schema(catalog_id, "sales")
    table_id = await app.add_table(catalog_id, schema_id, "orders")

    await app.change_schema(catalog_id, schema_id, new_name="revenue")
    await app.change_table(catalog_id, schema_id, table_id, new_name="purchases")

    assert (await app.get_table(catalog_id, schema_id, table_id)).name == "purchases"
    assert (await app.get_schema(catalog_id, schema_id)).name == "revenue"

    await app.discard_table(catalog_id, schema_id, table_id)
    await app.discard_schema(catalog_id, schema_id)

    assert (await app.get_catalog(catalog_id)).schemas == {}


async def test_unknown_ids_are_rejected(app: CatalogApplication) -> None:
    """An id that is not registered in the parent raises the domain error."""
    catalog_id = await app.create_catalog("analytics")
    await app.create_schema(catalog_id, "sales")

    with pytest.raises(UnknownSchemaError, match="does not exist"):
        await app.add_table(catalog_id, uuid4(), "orders")


async def test_add_field_normalises_the_data_type(app: CatalogApplication) -> None:
    """The application parses raw spellings before the aggregate records them."""
    catalog_id = await app.create_catalog("analytics")
    schema_id = await app.create_schema(catalog_id, "sales")
    table_id = await app.add_table(catalog_id, schema_id, "orders")

    await app.add_field(catalog_id, schema_id, table_id, "amount", "DECIMAL(10,2)")
    await app.change_field(catalog_id, schema_id, table_id, "amount", data_type="Numeric(10,2)")

    table = await app.get_table(catalog_id, schema_id, table_id)
    assert table.fields["amount"].data_type == DataType.parse("decimal(10,2)")

    events = await app.events.get(originator_id=table_id)
    added = next(event for event in events if isinstance(event, Table.FieldAdded))
    assert added.data_type == DataType.parse("decimal(10,2)")

