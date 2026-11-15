"""Tests for the PostgreSQL type mapper."""

import pytest

from etlalchemy.catalog.aggregates.types import DataType
from etlalchemy.ingestion.adapters.postgres import PostgresTypeMapper
from etlalchemy.ingestion.aggregates.errors import UnsupportedTypeError


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("boolean", "boolean"),
        ("smallint", "smallint"),
        ("integer", "integer"),
        ("bigint", "bigint"),
        ("real", "float"),
        ("double precision", "double"),
        ("numeric(10,2)", "decimal(10,2)"),
        ("numeric", "decimal"),
        ("character varying(255)", "varchar(255)"),
        ("character varying", "varchar"),
        ("character(3)", "char(3)"),
        ("text", "text"),
        ("xml", "text"),
        ("json", "json"),
        ("jsonb", "json"),
        ("bytea", "binary"),
        ("date", "date"),
        ("timestamp without time zone", "timestamp"),
        ("timestamp(6) with time zone", "timestamp"),
        ("uuid", "uuid"),
        ("money", "decimal(19,2)"),
    ],
)
def test_scalar_types_are_mapped(raw: str, expected: str) -> None:
    """Scalar PostgreSQL types map onto the catalog vocabulary."""
    assert PostgresTypeMapper().map(raw) == DataType.parse(expected)


def test_type_names_are_normalised() -> None:
    """Case and whitespace do not affect the mapping."""
    assert PostgresTypeMapper().map("  CHARACTER   VARYING(10)  ") == DataType.parse(
        "varchar(10)"
    )


def test_arrays_default_to_json() -> None:
    """Arrays become json by default."""
    mapper = PostgresTypeMapper()

    assert mapper.map("integer[]") == DataType.parse("json")
    assert mapper.map("character varying(10)[]") == DataType.parse("json")


def test_arrays_can_use_the_policy() -> None:
    """With array_as_json disabled the unsupported policy applies."""
    assert PostgresTypeMapper("skip", array_as_json=False).map("integer[]") is None
    assert PostgresTypeMapper("json", array_as_json=False).map("integer[]") == DataType.parse(
        "json"
    )
    with pytest.raises(UnsupportedTypeError, match="integer"):
        PostgresTypeMapper("fail", array_as_json=False).map("integer[]")


@pytest.mark.parametrize(
    "raw",
    ["time without time zone", "interval", "order_status", "bit varying(8)"],
)
def test_unsupported_types_follow_the_policy(raw: str) -> None:
    """Unsupported types fail, become json or are skipped as configured."""
    with pytest.raises(UnsupportedTypeError, match="Unsupported"):
        PostgresTypeMapper().map(raw)

    assert PostgresTypeMapper("json").map(raw) == DataType.parse("json")
    assert PostgresTypeMapper("skip").map(raw) is None


def test_overrides_win_over_builtin_mappings() -> None:
    """An explicit override maps a custom type without code changes."""
    mapper = PostgresTypeMapper(overrides={"order_status": "text"})

    assert mapper.map("ORDER_STATUS") == DataType.parse("text")
