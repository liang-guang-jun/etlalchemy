"""Tests for the canonical data type value object."""

import pytest

from etlalchemy.catalog.aggregates.errors import InvalidDataTypeError
from etlalchemy.catalog.aggregates.types import DataType


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("String", "string"),
        ("str", "string"),
        ("  TEXT  ", "text"),
        ("VARCHAR(255)", "varchar(255)"),
        ("varchar ( 255 )", "varchar(255)"),
        ("DECIMAL(10,2)", "decimal(10,2)"),
        ("Int", "integer"),
        ("int8", "bigint"),
        ("bool", "boolean"),
        ("datetime", "timestamp"),
        ("jsonb", "json"),
    ],
)
def test_parse_normalises(raw: str, expected: str) -> None:
    """Aliases, casing and whitespace normalise to the canonical text."""
    assert str(DataType.parse(raw)) == expected


@pytest.mark.parametrize("raw", ["", "varchar()", "string(10)", "money", "int(3,4)"])
def test_parse_rejects(raw: str) -> None:
    """Unknown types and parameters on non-parameterised types are rejected."""
    with pytest.raises(InvalidDataTypeError):
        DataType.parse(raw)


def test_parse_is_idempotent() -> None:
    """Parsing a data type or its text form returns the same value."""
    data_type = DataType.parse("VARCHAR(255)")
    assert DataType.parse(data_type) is data_type
    assert DataType.parse(str(data_type)) == data_type


def test_args_are_tuple_after_json_roundtrip() -> None:
    """JSON decodes ``args`` as a list; the value object keeps it hashable."""
    data_type = DataType(base="decimal", args=[10, 2])  # type: ignore[arg-type]
    assert data_type.args == (10, 2)
    assert hash(data_type)
