"""Tests for the change, discard and rename use cases of the catalog."""

from typing import Any
from uuid import UUID

import pytest
from etlalchemy.catalog.aggregates.catalog import Catalog
from etlalchemy.catalog.aggregates.errors import DiscardedError
from etlalchemy.catalog.aggregates.schema import Schema
from etlalchemy.catalog.aggregates.table import Table
from etlalchemy.catalog.application import CatalogApplication


@pytest.fixture
def application(catalog_app: CatalogApplication) -> CatalogApplication:
    """Returns a started catalog application on a temporary event store."""
    return catalog_app


async def has_event(
    application: CatalogApplication,
    aggregate_id: UUID,
    event_type: type[Any],
) -> bool:
    """Returns whether the aggregate stream holds an event of the given type."""
    events = await application.events.get(originator_id=aggregate_id)
    return any(isinstance(event, event_type) for event in events)


async def test_change_catalog_updates_name_and_description(
    application: CatalogApplication,
) -> None:
    """The change is stored on the catalog stream."""
    catalog_id = await application.create_catalog("analytics", "Original")

    await application.change_catalog(catalog_id, name="warehouse", description="Warehouse")

    catalog = await application.get_catalog(catalog_id)
    assert (catalog.name, catalog.description) == ("warehouse", "Warehouse")
    assert await has_event(application, catalog_id, Catalog.Changed)


async def test_discard_catalog_keeps_the_stream_and_blocks_changes(
    application: CatalogApplication,
) -> None:
    """A discarded catalog still loads but rejects further commands."""
    catalog_id = await application.create_catalog("analytics")

    await application.discard_catalog(catalog_id)

    catalog = await application.get_catalog(catalog_id)
    assert catalog._is_discarded is True
    assert await has_event(application, catalog_id, Catalog.Discarded)
    with pytest.raises(DiscardedError):
        await application.change_catalog(catalog_id, name="warehouse")


async def test_change_schema_writes_both_streams(application: CatalogApplication) -> None:
    """Renaming a schema updates the schema and the catalog registry."""
    catalog_id = await application.create_catalog("analytics")
    schema_id = await application.create_schema(catalog_id, "sales", "Sales data")

    await application.change_schema(
        catalog_id,
        "sales",
        new_name="revenue",
        new_description="Revenue data",
    )

    assert (await application.get_catalog(catalog_id)).schemas == {"revenue": schema_id}
    schema = await application.get_schema(catalog_id, "revenue")
    assert (schema.name, schema.description) == ("revenue", "Revenue data")
    assert await has_event(application, catalog_id, Catalog.SchemaNameChanged)
    assert await has_event(application, schema_id, Schema.Changed)


async def test_change_schema_without_a_name_keeps_the_registry(
    application: CatalogApplication,
) -> None:
    """A description-only change touches the schema stream only."""
    catalog_id = await application.create_catalog("analytics")
    schema_id = await application.create_schema(catalog_id, "sales")

    await application.change_schema(catalog_id, "sales", new_description="Updated")

    assert (await application.get_catalog(catalog_id)).schemas == {"sales": schema_id}
    assert (await application.get_schema(catalog_id, "sales")).description == "Updated"
    assert not await has_event(application, catalog_id, Catalog.SchemaNameChanged)


async def test_discard_schema_unregisters_and_discards(application: CatalogApplication) -> None:
    """The schema leaves the catalog registry but stays in the event store."""
    catalog_id = await application.create_catalog("analytics")
    schema_id = await application.create_schema(catalog_id, "sales")

    await application.discard_schema(catalog_id, "sales")

    assert (await application.get_catalog(catalog_id)).schemas == {}
    schema = await application.repository.get(schema_id)
    assert isinstance(schema, Schema)
    assert schema._is_discarded is True
    assert await has_event(application, schema_id, Schema.Discarded)


async def test_change_table_writes_both_streams(application: CatalogApplication) -> None:
    """Renaming a table updates the table and the schema registry."""
    catalog_id = await application.create_catalog("analytics")
    await application.create_schema(catalog_id, "sales")
    schema_id = (await application.get_schema(catalog_id, "sales")).id
    table_id = await application.add_table(catalog_id, "sales", "orders")

    await application.change_table(catalog_id, "sales", "orders", new_name="purchases")

    schema = await application.get_schema(catalog_id, "sales")
    assert schema.tables == {"purchases": table_id}
    assert (await application.get_table(catalog_id, "sales", "purchases")).name == "purchases"
    assert await has_event(application, schema_id, Schema.TableNameChanged)
    assert await has_event(application, table_id, Table.Changed)


async def test_change_table_description_keeps_the_registry(
    application: CatalogApplication,
) -> None:
    """A description-only change records one table event and leaves the names alone."""
    catalog_id = await application.create_catalog("analytics")
    await application.create_schema(catalog_id, "sales")
    table_id = await application.add_table(catalog_id, "sales", "orders")

    await application.change_table(
        catalog_id,
        "sales",
        "orders",
        new_description="Orders fact table",
    )

    table = await application.get_table(catalog_id, "sales", "orders")
    assert (table.name, table.description) == ("orders", "Orders fact table")
    assert (await application.get_schema(catalog_id, "sales")).tables == {"orders": table_id}
    assert await has_event(application, table_id, Table.Changed)


async def test_discard_table_unregisters_and_discards(application: CatalogApplication) -> None:
    """The table leaves the schema registry but stays in the event store."""
    catalog_id = await application.create_catalog("analytics")
    await application.create_schema(catalog_id, "sales")
    table_id = await application.add_table(catalog_id, "sales", "orders")

    await application.discard_table(catalog_id, "sales", "orders")

    assert (await application.get_schema(catalog_id, "sales")).tables == {}
    table = await application.repository.get(table_id)
    assert isinstance(table, Table)
    assert table._is_discarded is True
    assert await has_event(application, table_id, Table.Discarded)


async def test_rename_field_updates_the_table(application: CatalogApplication) -> None:
    """The field keeps its definition under the new name."""
    catalog_id = await application.create_catalog("analytics")
    await application.create_schema(catalog_id, "sales")
    table_id = await application.add_table(catalog_id, "sales", "orders")
    await application.add_field(catalog_id, "sales", "orders", "id", "bigint", nullable=False)

    await application.rename_field(catalog_id, "sales", "orders", "id", "order_id")

    table = await application.get_table(catalog_id, "sales", "orders")
    assert list(table.fields) == ["order_id"]
    field = table.fields["order_id"]
    assert (str(field.data_type), field.nullable) == ("bigint", False)
    assert await has_event(application, table_id, Table.FieldRenamed)


async def test_change_field_comment_records_the_change(application: CatalogApplication) -> None:
    """The comment is stored on the field and recorded as an event."""
    catalog_id = await application.create_catalog("analytics")
    await application.create_schema(catalog_id, "sales")
    table_id = await application.add_table(catalog_id, "sales", "orders")
    await application.add_field(catalog_id, "sales", "orders", "amount", "numeric")

    await application.change_field_comment(
        catalog_id,
        "sales",
        "orders",
        "amount",
        "Net revenue in EUR.",
    )

    table = await application.get_table(catalog_id, "sales", "orders")
    assert table.fields["amount"].comment == "Net revenue in EUR."
    assert await has_event(application, table_id, Table.FieldCommentChanged)
