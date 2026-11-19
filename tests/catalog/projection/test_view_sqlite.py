"""Tests for the SQLite catalog read model."""

from uuid import UUID, uuid4

import pytest
from etlalchemy.catalog.aggregates.types import DataType
from etlalchemy.catalog.projection.sqlalchemy import SQLAlchemyCatalogView
from etlalchemy.catalog.projection.view import (
    CatalogRow,
    FieldSearchResult,
    SchemaRow,
    TableRow,
)
from eventsourcing.persistence import IntegrityError, Tracking

UPSTREAM = "catalog-application"


@pytest.fixture
async def view(catalog_view: SQLAlchemyCatalogView) -> SQLAlchemyCatalogView:
    """Returns an empty view backed by a temporary database file."""
    return catalog_view


async def register_schema(
    view: SQLAlchemyCatalogView,
    catalog_id: UUID,
    name: str,
    tracking_id: int,
    description: str = "",
) -> UUID:
    """Registers a schema in the view and returns its ID."""
    schema_id = uuid4()
    await view.register_schema(schema_id, catalog_id, name, description, Tracking(UPSTREAM, tracking_id))
    return schema_id


async def register_table(
    view: SQLAlchemyCatalogView,
    schema_id: UUID,
    catalog_id: UUID,
    name: str,
    tracking_id: int,
) -> UUID:
    """Registers a table in the view and returns its ID."""
    table_id = uuid4()
    await view.register_table(table_id, schema_id, catalog_id, name, Tracking(UPSTREAM, tracking_id))
    return table_id


async def test_create_table_is_idempotent(view: SQLAlchemyCatalogView) -> None:
    """Creating the view tables twice does not fail."""
    await view.create_table()
    await view.create_table()


async def test_register_catalog_stores_the_row_and_tracks_the_event(
    view: SQLAlchemyCatalogView,
) -> None:
    """A registered catalog is queryable by id and listed by name."""
    catalog_id = uuid4()
    await view.register_catalog(
        catalog_id,
        "analytics",
        "Analytics warehouse",
        Tracking(UPSTREAM, 1),
    )

    expected = CatalogRow(catalog_id, "analytics", "Analytics warehouse")
    assert await view.get_catalog(catalog_id) == expected
    assert await view.list_catalogs() == [expected]
    assert await view.get_catalog(uuid4()) is None
    assert await view.max_tracking_id(UPSTREAM) == 1


async def test_register_catalog_is_idempotent(view: SQLAlchemyCatalogView) -> None:
    """Replaying Catalog.Started upserts instead of failing."""
    catalog_id = uuid4()
    await view.register_catalog(catalog_id, "analytics", "Analytics", Tracking(UPSTREAM, 1))
    await view.register_catalog(catalog_id, "analytics", "Analytics", Tracking(UPSTREAM, 2))

    assert await view.list_catalogs() == [CatalogRow(catalog_id, "analytics", "Analytics")]
    assert await view.max_tracking_id(UPSTREAM) == 2


async def test_list_catalogs_is_ordered_by_name(view: SQLAlchemyCatalogView) -> None:
    """Catalogs are returned in name order."""
    await view.register_catalog(uuid4(), "warehouse", "", Tracking(UPSTREAM, 1))
    await view.register_catalog(uuid4(), "analytics", "", Tracking(UPSTREAM, 2))

    assert [row.name for row in await view.list_catalogs()] == ["analytics", "warehouse"]


async def test_register_schema_stores_the_row_and_tracks_the_event(
    view: SQLAlchemyCatalogView,
) -> None:
    """A registered schema is queryable by id and by name."""
    catalog_id = uuid4()
    schema_id = await register_schema(view, catalog_id, "sales", tracking_id=1, description="Sales data")

    expected = SchemaRow(schema_id, catalog_id, "sales", "Sales data")
    assert await view.get_schema(schema_id) == expected
    assert await view.list_schemas(catalog_id) == [expected]
    assert await view.find_schema_id(catalog_id, "sales") == schema_id
    assert await view.find_schema_id(catalog_id, "warehouse") is None
    assert await view.get_schema(uuid4()) is None
    assert await view.max_tracking_id(UPSTREAM) == 1


async def test_tracking_conflict_rolls_back_the_view_change(view: SQLAlchemyCatalogView) -> None:
    """A duplicated notification id aborts the whole transaction."""
    catalog_id = uuid4()
    await register_schema(view, catalog_id, "sales", tracking_id=2)

    with pytest.raises(IntegrityError):
        await view.register_schema(uuid4(), catalog_id, "staging", "", Tracking(UPSTREAM, 2))

    assert [row.name for row in await view.list_schemas(catalog_id)] == ["sales"]
    assert await view.max_tracking_id(UPSTREAM) == 2


async def test_unregister_schema_cascades_to_tables_and_fields(
    view: SQLAlchemyCatalogView,
) -> None:
    """Removing a schema removes its tables and their fields."""
    catalog_id = uuid4()
    schema_id = await register_schema(view, catalog_id, "sales", tracking_id=1)
    table_id = await register_table(view, schema_id, catalog_id, "orders", tracking_id=2)
    await view.add_field(table_id, "id", DataType.parse("integer"), False, Tracking(UPSTREAM, 3))

    await view.unregister_schema(catalog_id, "sales", Tracking(UPSTREAM, 4))

    assert await view.list_schemas(catalog_id) == []
    assert await view.list_tables(schema_id) == []
    assert await view.list_fields(table_id) == []
    assert await view.max_tracking_id(UPSTREAM) == 4


async def test_register_table_and_lookup(view: SQLAlchemyCatalogView) -> None:
    """A registered table carries its schema and catalog ids."""
    catalog_id = uuid4()
    schema_id = await register_schema(view, catalog_id, "sales", tracking_id=1)
    table_id = await register_table(view, schema_id, catalog_id, "orders", tracking_id=2)

    expected = TableRow(table_id, schema_id, catalog_id, "orders")
    assert await view.get_table(table_id) == expected
    assert await view.list_tables(schema_id) == [expected]
    assert await view.find_table_id(schema_id, "orders") == table_id
    assert await view.find_table_id(schema_id, "customers") is None


async def test_unregister_table_cascades_to_fields(view: SQLAlchemyCatalogView) -> None:
    """Removing a table removes its fields but keeps the schema."""
    catalog_id = uuid4()
    schema_id = await register_schema(view, catalog_id, "sales", tracking_id=1)
    table_id = await register_table(view, schema_id, catalog_id, "orders", tracking_id=2)
    await view.add_field(table_id, "id", DataType.parse("integer"), False, Tracking(UPSTREAM, 3))

    await view.unregister_table(schema_id, "orders", Tracking(UPSTREAM, 4))

    assert await view.list_tables(schema_id) == []
    assert await view.list_fields(table_id) == []
    assert [row.name for row in await view.list_schemas(catalog_id)] == ["sales"]


async def test_add_and_remove_field(view: SQLAlchemyCatalogView) -> None:
    """Fields are stored per table and can be removed."""
    catalog_id = uuid4()
    schema_id = await register_schema(view, catalog_id, "sales", tracking_id=1)
    table_id = await register_table(view, schema_id, catalog_id, "orders", tracking_id=2)

    await view.add_field(table_id, "id", DataType.parse("integer"), False, Tracking(UPSTREAM, 3))
    await view.add_field(table_id, "note", DataType.parse("text"), True, Tracking(UPSTREAM, 4))

    assert [row.name for row in await view.list_fields(table_id)] == ["id", "note"]

    await view.remove_field(table_id, "note", Tracking(UPSTREAM, 5))

    rows = await view.list_fields(table_id)
    assert [row.name for row in rows] == ["id"]
    assert rows[0].data_type == DataType.parse("integer")
    assert rows[0].nullable is False


async def test_change_field_updates_only_non_none_values(view: SQLAlchemyCatalogView) -> None:
    """FieldTypeChanged/FieldNullabilityChanged only touch what they carry."""
    catalog_id = uuid4()
    schema_id = await register_schema(view, catalog_id, "sales", tracking_id=1)
    table_id = await register_table(view, schema_id, catalog_id, "orders", tracking_id=2)
    await view.add_field(table_id, "id", DataType.parse("integer"), False, Tracking(UPSTREAM, 3))

    await view.change_field(table_id, "id", DataType.parse("bigint"), None, Tracking(UPSTREAM, 4))

    assert (await view.list_fields(table_id))[0].data_type == DataType.parse("bigint")
    assert (await view.list_fields(table_id))[0].nullable is False

    await view.change_field(table_id, "id", None, True, Tracking(UPSTREAM, 5))

    assert (await view.list_fields(table_id))[0].data_type == DataType.parse("bigint")
    assert (await view.list_fields(table_id))[0].nullable is True


async def test_search_fields_matches_all_name_levels(view: SQLAlchemyCatalogView) -> None:
    """Search matches schema, table and field names across the read model."""
    catalog_id = uuid4()
    sales_id = await register_schema(view, catalog_id, "sales", tracking_id=1)
    staging_id = await register_schema(view, catalog_id, "staging", tracking_id=2)
    orders_id = await register_table(view, sales_id, catalog_id, "orders", tracking_id=3)
    raw_id = await register_table(view, staging_id, catalog_id, "raw_events", tracking_id=4)

    await view.add_field(orders_id, "order_id", DataType.parse("bigint"), False, Tracking(UPSTREAM, 5))
    await view.add_field(orders_id, "note", DataType.parse("text"), True, Tracking(UPSTREAM, 6))
    await view.add_field(raw_id, "payload", DataType.parse("jsonb"), True, Tracking(UPSTREAM, 7))

    by_field = await view.search_fields("note")
    assert by_field == [
        FieldSearchResult(
            catalog_id=catalog_id,
            schema_id=sales_id,
            schema_name="sales",
            table_id=orders_id,
            table_name="orders",
            field_name="note",
            data_type=DataType.parse("text"),
            nullable=True,
        )
    ]

    for term, expected in [
        ("sales", {"note", "order_id"}),
        ("raw", {"payload"}),
        ("ord", {"note", "order_id"}),
    ]:
        found = {row.field_name for row in await view.search_fields(term)}
        assert found == expected, term

    assert await view.search_fields("note", catalog_id=uuid4()) == []


async def test_change_catalog_updates_only_the_given_attributes(view: SQLAlchemyCatalogView) -> None:
    """A None attribute keeps the stored value."""
    catalog_id = uuid4()
    await view.register_catalog(catalog_id, "analytics", "Original", Tracking(UPSTREAM, 1))

    await view.change_catalog(catalog_id, "warehouse", None, Tracking(UPSTREAM, 2))

    changed = await view.get_catalog(catalog_id)
    assert changed is not None
    assert (changed.name, changed.description) == ("warehouse", "Original")


async def test_discard_catalog_hides_the_catalog_and_its_children(
    view: SQLAlchemyCatalogView,
) -> None:
    """Discarding a catalog hides its schemas, tables and fields."""
    catalog_id = uuid4()
    await view.register_catalog(catalog_id, "analytics", "", Tracking(UPSTREAM, 1))
    schema_id = await register_schema(view, catalog_id, "sales", tracking_id=2)
    table_id = await register_table(view, schema_id, catalog_id, "orders", tracking_id=3)
    await view.add_field(table_id, "id", DataType.parse("integer"), False, Tracking(UPSTREAM, 4))

    await view.discard_catalog(catalog_id, Tracking(UPSTREAM, 5))

    assert await view.get_catalog(catalog_id) is None
    assert await view.list_catalogs() == []
    assert await view.list_schemas(catalog_id) == []
    assert await view.list_tables(schema_id) == []
    assert await view.list_fields(table_id) == []
    assert await view.find_schema_id(catalog_id, "sales") is None
    assert await view.search_fields("orders") == []
    assert await view.max_tracking_id(UPSTREAM) == 5


async def test_discard_schema_hides_the_schema_and_its_tables(view: SQLAlchemyCatalogView) -> None:
    """Discarding a schema keeps the catalog but hides the subtree."""
    catalog_id = uuid4()
    await view.register_catalog(catalog_id, "analytics", "", Tracking(UPSTREAM, 1))
    schema_id = await register_schema(view, catalog_id, "sales", tracking_id=2)
    table_id = await register_table(view, schema_id, catalog_id, "orders", tracking_id=3)
    await view.add_field(table_id, "id", DataType.parse("integer"), False, Tracking(UPSTREAM, 4))

    await view.discard_schema(schema_id, Tracking(UPSTREAM, 5))

    assert await view.get_schema(schema_id) is None
    assert await view.list_schemas(catalog_id) == []
    assert await view.get_table(table_id) is None
    assert await view.list_fields(table_id) == []
    assert await view.get_catalog(catalog_id) is not None


async def test_discard_table_hides_the_table_and_drops_its_fields(
    view: SQLAlchemyCatalogView,
) -> None:
    """Discarding a table keeps the schema but hides the table."""
    catalog_id = uuid4()
    await view.register_catalog(catalog_id, "analytics", "", Tracking(UPSTREAM, 1))
    schema_id = await register_schema(view, catalog_id, "sales", tracking_id=2)
    table_id = await register_table(view, schema_id, catalog_id, "orders", tracking_id=3)
    await view.add_field(table_id, "id", DataType.parse("integer"), False, Tracking(UPSTREAM, 4))

    await view.discard_table(table_id, Tracking(UPSTREAM, 5))

    assert await view.get_table(table_id) is None
    assert await view.list_tables(schema_id) == []
    assert await view.list_fields(table_id) == []
    assert await view.get_schema(schema_id) is not None


async def test_change_schema_and_table_rename_the_rows(view: SQLAlchemyCatalogView) -> None:
    """Renaming a schema or a table updates the stored name."""
    catalog_id = uuid4()
    await view.register_catalog(catalog_id, "analytics", "", Tracking(UPSTREAM, 1))
    schema_id = await register_schema(view, catalog_id, "sales", tracking_id=2, description="Sales")
    table_id = await register_table(view, schema_id, catalog_id, "orders", tracking_id=3)

    await view.change_schema(schema_id, "revenue", None, Tracking(UPSTREAM, 4))
    await view.change_table(table_id, "purchases", Tracking(UPSTREAM, 5))

    assert await view.find_schema_id(catalog_id, "revenue") == schema_id
    assert await view.find_schema_id(catalog_id, "sales") is None
    schema = await view.get_schema(schema_id)
    assert schema is not None
    assert (schema.name, schema.description) == ("revenue", "Sales")
    assert await view.find_table_id(schema_id, "purchases") == table_id
    assert await view.find_table_id(schema_id, "orders") is None


async def test_rename_field_moves_the_definition(view: SQLAlchemyCatalogView) -> None:
    """The renamed field keeps its type and nullability."""
    catalog_id = uuid4()
    schema_id = await register_schema(view, catalog_id, "sales", tracking_id=1)
    table_id = await register_table(view, schema_id, catalog_id, "orders", tracking_id=2)
    await view.add_field(table_id, "id", DataType.parse("bigint"), False, Tracking(UPSTREAM, 3))

    await view.rename_field(table_id, "id", "order_id", Tracking(UPSTREAM, 4))

    fields = [
        (row.name, str(row.data_type), row.nullable) for row in await view.list_fields(table_id)
    ]
    assert fields == [("order_id", "bigint", False)]


async def test_change_field_stores_the_comment(view: SQLAlchemyCatalogView) -> None:
    """The comment of a field is stored next to its type and nullability."""
    catalog_id = uuid4()
    schema_id = await register_schema(view, catalog_id, "sales", tracking_id=1)
    table_id = await register_table(view, schema_id, catalog_id, "orders", tracking_id=2)
    await view.add_field(table_id, "amount", DataType.parse("numeric"), True, Tracking(UPSTREAM, 3))

    await view.change_field(table_id, "amount", None, None, Tracking(UPSTREAM, 4), comment="Net")

    fields = await view.list_fields(table_id)
    assert [(row.name, row.comment) for row in fields] == [("amount", "Net")]


async def test_rename_field_replaces_a_conflicting_field(view: SQLAlchemyCatalogView) -> None:
    """Renaming onto an existing name replaces that field."""
    catalog_id = uuid4()
    schema_id = await register_schema(view, catalog_id, "sales", tracking_id=1)
    table_id = await register_table(view, schema_id, catalog_id, "orders", tracking_id=2)
    await view.add_field(table_id, "id", DataType.parse("bigint"), False, Tracking(UPSTREAM, 3))
    await view.add_field(table_id, "note", DataType.parse("text"), True, Tracking(UPSTREAM, 4))

    await view.rename_field(table_id, "id", "note", Tracking(UPSTREAM, 5))

    fields = [
        (row.name, str(row.data_type), row.nullable) for row in await view.list_fields(table_id)
    ]
    assert fields == [("note", "bigint", False)]


async def test_a_discarded_name_can_be_reused(view: SQLAlchemyCatalogView) -> None:
    """A discarded schema or table keeps its row but frees its name."""
    catalog_id = uuid4()
    await view.register_catalog(catalog_id, "analytics", "", Tracking(UPSTREAM, 1))
    old_schema_id = await register_schema(view, catalog_id, "sales", tracking_id=2)
    await view.unregister_schema(catalog_id, "sales", Tracking(UPSTREAM, 3))

    new_schema_id = await register_schema(view, catalog_id, "sales", tracking_id=4)

    assert await view.find_schema_id(catalog_id, "sales") == new_schema_id
    assert await view.get_schema(old_schema_id) is None
    assert [row.schema_id for row in await view.list_schemas(catalog_id)] == [new_schema_id]
