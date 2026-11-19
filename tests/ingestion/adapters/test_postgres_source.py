"""Tests for the PostgreSQL source adapter using a fake async connection."""

from typing import Any

import pytest
from etlalchemy.ingestion.adapters.postgres import PostgresSource, PostgresTypeMapper
from etlalchemy.ingestion.aggregates.errors import UnknownCatalogError


class FakeCursor:
    """Minimal cursor that returns a preset list of rows."""

    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    async def fetchone(self) -> Any:
        """Returns the first row, or ``None``."""
        return self._rows[0] if self._rows else None

    async def fetchall(self) -> list[Any]:
        """Returns every row."""
        return list(self._rows)


class FakeConnection:
    """Records statements and returns one preset result per call."""

    def __init__(self, *results: list[Any]) -> None:
        self._results = list(results)
        self.calls: list[tuple[str, Any]] = []
        self.closed = False

    async def execute(self, sql: str, params: Any = None) -> FakeCursor:
        """Records the statement and returns the next preset result."""
        self.calls.append((sql, params))
        return FakeCursor(self._results.pop(0))

    async def close(self) -> None:
        """Records the close."""
        self.closed = True


def build(*results: list[Any], include_views: bool = False) -> tuple[PostgresSource, FakeConnection]:
    """Builds a source over a fake connection with the given results."""
    connection = FakeConnection(*results)
    return (
        PostgresSource(connection, PostgresTypeMapper(), include_views=include_views),
        connection,
    )


async def test_list_catalogs_returns_the_current_database() -> None:
    """PostgreSQL exposes only the database of the connection."""
    source, _ = build([("analytics",)])

    assert await source.list_catalogs() == ["analytics"]


async def test_list_schemas_rejects_another_database() -> None:
    """A catalog other than the current database is rejected."""
    source, _ = build([("analytics",)])

    with pytest.raises(UnknownCatalogError, match="warehouse"):
        await source.list_schemas("warehouse")


async def test_list_schemas_returns_the_names() -> None:
    """The visible schema names are returned in query order."""
    source, _ = build([("analytics",)], [("public",), ("sales",)])

    assert await source.list_schemas("analytics") == ["public", "sales"]


async def test_list_tables_passes_the_schema_and_relkinds() -> None:
    """Table names are parameterised and only base/partitioned tables are read."""
    source, connection = build([("orders",)])

    assert await source.list_tables("analytics", "sales") == ["orders"]
    sql, params = connection.calls[0]
    assert params == ("sales", ["r", "p"])
    assert "sales" not in sql


async def test_include_views_adds_view_relkinds() -> None:
    """Enabling views adds views, materialised views and foreign tables."""
    source, connection = build([("order_totals",), ("orders",)], include_views=True)

    assert await source.list_tables("analytics", "sales") == ["order_totals", "orders"]
    _, params = connection.calls[0]
    assert params == ("sales", ["r", "p", "v", "m", "f"])


async def test_list_columns_builds_column_info() -> None:
    """Column rows become ``ColumnInfo`` values with nullability."""
    source, _ = build([("id", "bigint", False), ("note", "text", True)])

    columns = await source.list_columns("analytics", "sales", "orders")

    assert [(column.name, column.raw_type, column.nullable) for column in columns] == [
        ("id", "bigint", False),
        ("note", "text", True),
    ]


async def test_column_query_is_parameterised() -> None:
    """Schema and table names never appear in the SQL text."""
    source, connection = build([("id", "bigint", False)])

    await source.list_columns("analytics", "sales", "orders")

    sql, params = connection.calls[0]
    assert params == ("sales", "orders")
    assert "sales" not in sql
    assert "orders" not in sql


async def test_close_releases_the_connection() -> None:
    """Closing the source closes the underlying connection."""
    source, connection = build()

    await source.close()

    assert connection.closed is True
