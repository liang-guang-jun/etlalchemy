"""Tests for reflecting live tables and mapping them to semantic rowsets."""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from etlalchemy.reflect import (
    ReflectedColumn,
    ReflectedTable,
    as_entities,
    map_type,
)
from etlalchemy.semantic.identifier import QualifiedName
from etlalchemy.semantic.types import (
    Boolean,
    Decimal,
    Float,
    Integer,
    Json,
    String,
    Timestamp,
    Uuid,
)
from reflect.helpers import add_table, reflected_tables, sqlite_source


def test_reflect_tables_reads_columns_and_primary_keys(tmp_path: Path) -> None:
    """reflection returns the tables, their columns and their primary keys."""
    source = sqlite_source(tmp_path)

    tables = reflected_tables(source)

    assert [table.name for table in tables] == ["orders", "users"]
    users = tables[1]
    assert [column.name for column in users.columns] == [
        "id",
        "name",
        "balance",
        "created_at",
        "active",
        "avatar",
    ]
    assert users.primary_key == ("id",)
    nullable = {column.name: column.nullable for column in users.columns}
    assert nullable["name"] is False
    assert nullable["balance"] is True


def test_reflect_tables_honours_a_table_selection(tmp_path: Path) -> None:
    """Only the tables named by the call are reflected."""
    source = sqlite_source(tmp_path)

    tables = reflected_tables(source, table_names=("users",))

    assert [table.name for table in tables] == ["users"]


def test_as_entities_maps_types_and_aliases(tmp_path: Path) -> None:
    """Columns become typed fields and aliases override the entity alias."""
    source = sqlite_source(tmp_path)

    entities = as_entities(
        reflected_tables(source),
        aliases={"users": "customers"},
    )

    rowsets = {entity.relation.sql_name: entity.relation for entity in entities}
    aliases = {entity.relation.sql_name: entity.alias for entity in entities}
    assert aliases == {"orders": "orders", "users": "customers"}
    users = rowsets["users"]
    assert users.primary_key == ["id"]
    assert users.fields["id"].data_type == Integer()
    assert users.fields["name"].data_type == String(20)
    assert users.fields["active"].data_type == Boolean()
    assert users.fields["created_at"].data_type == Timestamp()
    assert rowsets["orders"].fields["total"].data_type == Float()


def test_map_type_accepts_cached_strings_and_falls_back() -> None:
    """Cached type strings map to semantic types and unknown ones fall back."""
    assert map_type("VARCHAR(64)") == String(64)
    assert map_type("DECIMAL(10,2)") == Decimal(10, 2)
    assert map_type("TIMESTAMP") == Timestamp()
    assert map_type("JSON") == Json()
    assert map_type("UUID") == Uuid()
    assert map_type("geography") == String()


def test_added_table_is_reflected_on_a_forced_run(tmp_path: Path) -> None:
    """A forced reflection sees a table that the first run did not know."""
    source = sqlite_source(tmp_path)
    assert [table.name for table in reflected_tables(source)] == ["orders", "users"]

    add_table(source, "payments")

    refreshed = reflected_tables(source, force=True)

    assert [table.name for table in refreshed] == ["orders", "payments", "users"]


def test_as_rowset_keeps_the_primary_key_and_the_live_types(tmp_path: Path) -> None:
    """A reflected table turns into a table-backed rowset."""
    source = sqlite_source(tmp_path)

    users = reflected_tables(source, table_names=("users",))[0]
    rowset = users.as_rowset()

    assert rowset.sql_name == "users"
    assert rowset.primary_key == ["id"]
    assert rowset.fields["id"].data_type == Integer()
    assert isinstance(users.sqlalchemy_table, sa.Table)
    assert rowset.fields["name"].data_type == String(20)


def test_as_entity_gives_every_call_a_new_entity(tmp_path: Path) -> None:
    """Each call builds a fresh entity and a fresh rowset."""
    source = sqlite_source(tmp_path)

    orders = reflected_tables(source, table_names=("orders",))[0]
    first = orders.as_entity(alias="sales")
    second = orders.as_entity()

    assert first.alias == "sales"
    assert second.alias == "orders"
    assert first.id != second.id
    assert first.relation is not second.relation
    assert second.relation.sql_name == "orders"


def test_as_rowset_maps_cached_type_strings() -> None:
    """A cached table has no live table and maps its stored type strings."""
    table = ReflectedTable(
        name="cities",
        columns=(
            ReflectedColumn(name="id", sa_type="INTEGER", nullable=False),
            ReflectedColumn(name="name", sa_type="VARCHAR(32)", nullable=True),
        ),
        primary_key=("id",),
    )

    rowset = table.as_rowset(name="locations")

    assert table.sqlalchemy_table is None
    assert rowset.sql_name == "locations"
    assert rowset.primary_key == ["id"]
    assert rowset.fields["id"].data_type == Integer()
    assert rowset.fields["name"].data_type == String(32)


def test_as_rowset_without_a_primary_key_has_none() -> None:
    """A table with no primary key becomes a rowset without one."""
    table = ReflectedTable(name="log", columns=(), primary_key=())

    assert table.as_rowset().primary_key is None


def test_as_rowset_falls_back_when_the_live_table_lacks_a_column() -> None:
    """A live table without the reflected column uses the reflected type."""
    live = sa.Table(
        "cities",
        sa.MetaData(),
        sa.Column("id", sa.Integer),
    )
    table = ReflectedTable(
        name="cities",
        columns=(
            ReflectedColumn(name="id", sa_type="INTEGER", nullable=False),
            ReflectedColumn(name="nickname", sa_type="VARCHAR(12)", nullable=True),
        ),
        primary_key=(),
        sqlalchemy_table=live,
    )

    rowset = table.as_rowset()

    assert rowset.fields["id"].data_type == Integer()
    assert rowset.fields["nickname"].data_type == String(12)


def test_as_rowset_accepts_a_qualified_name() -> None:
    """A reflected table can keep the catalog and schema it was read from."""
    table = ReflectedTable(
        name="test",
        columns=(ReflectedColumn(name="id", sa_type="INTEGER", nullable=False),),
        primary_key=("id",),
    )

    rowset = table.as_rowset(
        QualifiedName("test", schema="default", catalog="main")
    )

    assert rowset.sql_name == "main.default.test"
