"""Tests for the SQLAlchemy type mapping."""

from __future__ import annotations

import sqlalchemy as sa
from etlalchemy.reflect import map_type, type_to_string
from etlalchemy.semantic.types import (
    Binary,
    Boolean,
    DataType,
    Date,
    Decimal,
    Float,
    Integer,
    Json,
    String,
    Timestamp,
    Uuid,
)


def test_map_type_handles_common_sqlalchemy_instances() -> None:
    """Every supported SQLAlchemy type maps to its semantic counterpart."""
    mapping: list[tuple[object, DataType]] = [
        (sa.Integer(), Integer()),
        (sa.BigInteger(), Integer()),
        (sa.SmallInteger(), Integer()),
        (sa.String(64), String(64)),
        (sa.Text(), String()),
        (sa.Float(), Float()),
        (sa.Numeric(10, 2), Decimal(10, 2)),
        (sa.Boolean(), Boolean()),
        (sa.Date(), Date()),
        (sa.DateTime(), Timestamp()),
        (sa.DateTime(timezone=True), Timestamp(timezone=True)),
        (sa.LargeBinary(16), Binary(16)),
        (sa.JSON(), Json()),
        (sa.Uuid(), Uuid()),
    ]

    for sa_type, expected in mapping:
        assert map_type(sa_type) == expected


def test_map_type_handles_cached_type_strings() -> None:
    """Cached type strings map like the instances they came from."""
    mapping: dict[str, DataType] = {
        "VARCHAR(64)": String(64),
        "TEXT": String(),
        "INTEGER": Integer(),
        "BIGINT": Integer(),
        "NUMERIC(10,2)": Decimal(10, 2),
        "DECIMAL": Decimal(38),
        "FLOAT": Float(),
        "BOOLEAN": Boolean(),
        "DATE": Date(),
        "TIMESTAMP": Timestamp(),
        "BLOB(16)": Binary(16),
        "JSON": Json(),
        "UUID": Uuid(),
    }

    for text, expected in mapping.items():
        assert map_type(text) == expected


def test_map_type_falls_back_to_string_for_unknown_types() -> None:
    """An unknown type never stops the reflection."""
    assert map_type("geography") == String()
    assert map_type(object()) == String()


def test_type_to_string_renders_arguments() -> None:
    """Instances render as class name plus arguments, strings pass through."""
    assert type_to_string(sa.String(64)) == "String(64)"
    assert type_to_string(sa.Numeric(10, 2)) == "Numeric(10,2)"
    assert type_to_string(sa.Boolean()) == "Boolean"
    assert type_to_string("VARCHAR(64)") == "VARCHAR(64)"


def test_type_string_round_trips_through_map_type() -> None:
    """A rendered type string maps back to the same semantic type."""
    for sa_type in (
        sa.Integer(),
        sa.String(64),
        sa.Numeric(10, 2),
        sa.DateTime(timezone=True),
        sa.LargeBinary(16),
    ):
        rendered = type_to_string(sa_type)
        assert map_type(rendered) == map_type(sa_type)
