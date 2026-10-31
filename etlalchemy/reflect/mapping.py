"""Map SQLAlchemy column metadata onto semantic data types.

``map_type`` accepts either a SQLAlchemy type instance or the type string a
cache stores. Instance mapping uses ``isinstance`` so subclasses such as
``TEXT``, ``BIGINT`` and ``TIMESTAMP`` are covered. A type that is not
recognised falls back to :class:`~etlalchemy.semantic.types.String` instead of
raising, so one unusual column never stops a whole reflection run.
"""

from __future__ import annotations

import re

import sqlalchemy as sa

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

#: Attributes serialised as the arguments of a type string.
_TYPE_ARGUMENTS = ("length", "precision", "scale", "timezone")

#: Base names of string types, lowercased.
_STRING_TYPES = frozenset({"string", "varchar", "text", "char", "unicode"})

#: Base names of integer types, lowercased.
_INTEGER_TYPES = frozenset({"integer", "biginteger", "smallinteger", "int", "bigint"})

#: Base names of exact numeric types, lowercased.
_DECIMAL_TYPES = frozenset({"numeric", "decimal"})

#: Base names of binary types, lowercased.
_BINARY_TYPES = frozenset({"largebinary", "binary", "blob", "varbinary"})


def map_type(sa_type: object) -> DataType:
    """Map a SQLAlchemy type or type string to a semantic data type.

    SQLAlchemy instances are matched first, then type strings such as
    ``"VARCHAR(64)"`` or ``"DECIMAL(10,2)"``. Anything else becomes an
    unbounded ``String``.

    Args:
        sa_type: SQLAlchemy type instance or the cached type string.

    Returns:
        The matching semantic data type.
    """
    if isinstance(sa_type, str):
        return _map_type_string(sa_type)
    if isinstance(sa_type, sa.Boolean):
        return Boolean()
    if isinstance(sa_type, sa.Integer):
        return Integer()
    if isinstance(sa_type, sa.Numeric):
        precision = getattr(sa_type, "precision", None) or 38
        scale = getattr(sa_type, "scale", None)
        return Decimal(precision, scale)
    if isinstance(sa_type, sa.Float):
        return Float()
    if isinstance(sa_type, sa.LargeBinary):
        return Binary(getattr(sa_type, "length", None))
    if isinstance(sa_type, (sa.String, sa.Text, sa.Unicode)):
        return String(getattr(sa_type, "length", None))
    if isinstance(sa_type, sa.JSON):
        return Json()
    if isinstance(sa_type, sa.Uuid):
        return Uuid()
    if isinstance(sa_type, sa.DateTime):
        return Timestamp(timezone=bool(getattr(sa_type, "timezone", False)))
    if isinstance(sa_type, sa.Date):
        return Date()
    return String()


def type_to_string(sa_type: object) -> str:
    """Return the stable string form of a column type.

    SQLAlchemy instances render as ``"ClassName(arg1,arg2)"`` with their known
    arguments; strings are returned unchanged so a cached type string can be
    serialised again.

    Args:
        sa_type: SQLAlchemy type instance or a type string.

    Returns:
        The type as a string.
    """
    if isinstance(sa_type, str):
        return sa_type
    name = type(sa_type).__name__
    arguments = [
        str(value)
        for value in (
            getattr(sa_type, attribute, None) for attribute in _TYPE_ARGUMENTS
        )
        if value is not None and value is not False
    ]
    return f"{name}({','.join(arguments)})" if arguments else name


def _map_type_string(sa_type: str) -> DataType:
    """Map a type string such as ``"VARCHAR(64)"``."""
    lowered = sa_type.strip().lower()
    name = re.split(r"[(\s]", lowered, maxsplit=1)[0]
    integers = _integers(lowered)
    first = _first_int(integers)
    if name in _STRING_TYPES:
        return String(first)
    if name in _INTEGER_TYPES:
        return Integer()
    if name in _DECIMAL_TYPES:
        return Decimal(first or 38, _nth_int(integers, 1))
    if name in {"float", "double", "real"}:
        return Float()
    if name in {"boolean", "bool"}:
        return Boolean()
    if name == "date":
        return Date()
    if name in {"datetime", "timestamp", "timestamptz", "timestamp_tz"}:
        timezone = "tz" in name or "(true)" in lowered
        return Timestamp(timezone=timezone)
    if name in _BINARY_TYPES:
        return Binary(first)
    if name == "json":
        return Json()
    if name == "uuid":
        return Uuid()
    return String()


def _integers(text: str) -> list[int]:
    """Return every integer written in a type string."""
    return [int(match) for match in re.findall(r"\d+", text)]


def _first_int(integers: list[int]) -> int | None:
    """Return the first integer of a type string, if any."""
    return integers[0] if integers else None


def _nth_int(integers: list[int], index: int) -> int | None:
    """Return the integer at ``index`` of a type string, if any."""
    return integers[index] if len(integers) > index else None


__all__ = ["map_type", "type_to_string"]
